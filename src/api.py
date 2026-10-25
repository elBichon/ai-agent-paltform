import os
import logging
import time
import asyncio
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, Depends, HTTPException, Header
from pydantic import BaseModel
from psycopg2 import pool
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager
from dotenv import load_dotenv
import litellm
import uuid
import base64
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import json
import socket
import ipaddress
import os

# 1. Application Base Logger
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

load_dotenv()

app = FastAPI(title="AI Platform API")


DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable is not set")
# Database Configuration


# Global pool variable
db_pool = None


def get_api_decryption_cipher():
    secret_key = os.getenv("FLASK_SECRET_KEY", "dev_secret_key")
    salt = b'fixed_salt'

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(secret_key.encode()))
    return Fernet(key)


def decrypt_model_api_key(cipher_text: str) -> str:
    if not cipher_text:
        return ""
    try:
        f = get_api_decryption_cipher()
        return f.decrypt(cipher_text.encode()).decode()
    except Exception:
        raise HTTPException(
            status_code=502,
            detail="Cryptography error: Failed to decrypt model API credentials."
        )


def init_pool():
    global db_pool
    if db_pool is not None:
        return db_pool

    if not DATABASE_URL:
        logger.error("DATABASE_URL environment variable is missing!")
        return None

    try:
        db_pool = pool.ThreadedConnectionPool(
            1, 20, DATABASE_URL,
            connect_timeout=10,
            keepalives=1,
            keepalives_idle=30,
            keepalives_interval=10,
            keepalives_count=5
        )
        logger.info("Database connection pool created successfully")
        return db_pool
    except Exception as e:
        logger.error(f"Error creating connection pool: {e}")
        return None


@contextmanager
def get_db_cursor():
    pool_instance = init_pool()
    if pool_instance is None:
        raise HTTPException(status_code=500, detail="Database connection pool could not be initialized.")

    conn = pool_instance.getconn()
    cur = None
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        yield cur
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        if cur:
            cur.close()
        pool_instance.putconn(conn)


def log_trace_to_db(trace_log: dict):
    try:
        with get_db_cursor() as cur:
            cur.execute("""
                INSERT INTO api_gateway_logs (
                    trace_id, user_id, agent_id, requested_model_id,
                    input_query_length, input_query, user_email,
                    resolved_model_name, evaluated_groups, status,
                    latency_seconds, output_response, error_type,
                    error_message, http_status_code, prompt_tokens,
                    completion_tokens, total_tokens, estimated_cost_usd
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
            """, (
                trace_log.get("trace_id"),
                trace_log.get("user_id"),
                trace_log.get("agent_id"),
                trace_log.get("requested_model_id"),
                trace_log.get("input_query_length", 0),
                trace_log.get("input_query", ""),
                trace_log.get("user_email", "unknown@system"),
                trace_log.get("resolved_model_name", "unknown"),
                trace_log.get("evaluated_groups", []),  # <-- RETIRER json.dumps() ici pour laisser psycopg2 gérer la liste nativement
                trace_log.get("status", "unknown"),
                trace_log.get("latency_seconds", 0.0),
                trace_log.get("output_response"),
                trace_log.get("error_type"),
                trace_log.get("error_message"),
                trace_log.get("http_status_code"),
                trace_log.get("prompt_tokens", 0),
                trace_log.get("completion_tokens", 0),
                trace_log.get("total_tokens", 0),
                trace_log.get("estimated_cost_usd", 0.0)
            ))
    except Exception as log_err:
        logger.error(f"❌ Failed to persist trace log to api_gateway_logs table: {log_err}")


RATE_LIMIT = 60
request_history = {}


def check_rate_limit(api_key: str):
    now = time.time()
    if api_key not in request_history:
        request_history[api_key] = []

    request_history[api_key] = [t for t in request_history[api_key] if now - t < 60]

    if len(request_history[api_key]) >= RATE_LIMIT:
        raise HTTPException(status_code=429, detail="Too Many Requests")

    request_history[api_key].append(now)


async def verify_api_key(x_api_key: str = Header(...)):
    if not x_api_key:
        raise HTTPException(status_code=401, detail="API Key missing")

    with get_db_cursor() as cur:
        cur.execute("SELECT user_id FROM api_keys WHERE key_value = %s", (x_api_key,))
        result = cur.fetchone()
        if not result:
            raise HTTPException(status_code=401, detail="Invalid API Key")

        check_rate_limit(x_api_key)
        return result['user_id']


class AgentRequest(BaseModel):
    agent_id: str
    user_query: str
    model_id: str
    rag_path: Optional[str] = None
    prompt_version: Optional[int] = None


@app.post("/v1/call_agent")
async def call_agent(agent_req: AgentRequest, user_id: uuid.UUID = Depends(verify_api_key)):
    trace_id_str = str(uuid.uuid4())
    start_time = time.perf_counter()
    
    semantica_decision_id: Optional[str] = None
    quota_reserved_groups = []

    trace_log = {
        "trace_id": trace_id_str,
        "user_id": str(user_id),
        "agent_id": str(agent_req.agent_id),
        "requested_model_id": str(agent_req.model_id),
        "requested_prompt_version": agent_req.prompt_version,
        "resolved_prompt_version": None,
        "input_query_length": len(agent_req.user_query),
        "input_query": agent_req.user_query,
        "user_email": "unknown@system",
        "resolved_model_name": "unknown",
        "evaluated_groups": [],
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "estimated_cost_usd": 0.0
    }

    try:
        def fetch_pipeline_data_atomic():
            with get_db_cursor() as cur:
                cur.execute("SELECT email FROM users WHERE id = %s", (str(user_id),))
                user_row = cur.fetchone()
                if not user_row:
                    raise HTTPException(status_code=404, detail="User tracking row missing.")
                email = user_row["email"]

                cur.execute("SELECT name, base_url, api_key FROM models WHERE id = %s", (str(agent_req.model_id),))
                model = cur.fetchone()
                if not model:
                    raise HTTPException(status_code=404, detail="Specified model not found")

                cur.execute("""
                    SELECT mc.group_name, mc.max_calls, COALESCE(gmu.call_count, 0) as current_usage
                    FROM model_constraints mc
                    JOIN user_groups ug ON mc.group_name = ug.group_name
                    LEFT JOIN group_model_usage gmu ON mc.group_name = gmu.group_name 
                        AND mc.model_id = gmu.model_id AND gmu.usage_date = CURRENT_DATE
                    WHERE ug.user_email = %s AND mc.model_id = %s
                """, (email, str(agent_req.model_id)))
                constraints = cur.fetchall()

                for constraint in constraints:
                    if constraint["max_calls"] is not None and constraint["current_usage"] >= constraint["max_calls"]:
                        raise HTTPException(
                            status_code=403,
                            detail=f"Resource access denied: Daily limit exhausted for group '{constraint['group_name']}'."
                        )

                reserved = []
                for constraint in constraints:
                    cur.execute("""
                        INSERT INTO group_model_usage (group_name, model_id, usage_date, call_count)
                        VALUES (%s, %s, CURRENT_DATE, 1)
                        ON CONFLICT (group_name, model_id, usage_date)
                        DO UPDATE SET call_count = group_model_usage.call_count + 1
                    """, (constraint["group_name"], str(agent_req.model_id)))
                    reserved.append(constraint["group_name"])

                cur.execute("""
                    SELECT a.name, a.paused, a.rag_enabled FROM agents a
                    LEFT JOIN user_agent_suite uas ON a.id = uas.agent_id AND uas.user_id = %s
                    WHERE a.id = %s AND (a.creator_user_id = %s OR uas.user_id IS NOT NULL)
                """, (str(user_id), str(agent_req.agent_id), str(user_id)))
                agent_data = cur.fetchone()
                if not agent_data:
                    raise HTTPException(status_code=404, detail="Agent not found or access denied")

                if agent_data.get("paused"):
                    raise HTTPException(
                        status_code=403,
                        detail=f"Agent '{agent_data['name']}' is currently paused."
                    )

                if agent_req.prompt_version is not None:
                    cur.execute("""
                        SELECT prompt, rules, skills, version 
                        FROM prompt_system_versions 
                        WHERE agent_id = %s AND version = %s
                    """, (str(agent_req.agent_id), agent_req.prompt_version))
                    prompts = cur.fetchone()
                    if not prompts:
                        raise HTTPException(
                            status_code=404, 
                            detail=f"Prompt system version '{agent_req.prompt_version}' not found."
                        )
                else:
                    cur.execute("""
                        SELECT prompt, rules, skills, version 
                        FROM prompt_system_versions 
                        WHERE agent_id = %s 
                        ORDER BY version DESC LIMIT 1
                    """, (str(agent_req.agent_id),))
                    prompts = cur.fetchone() or {"prompt": "", "rules": "", "skills": "", "version": None}

                # --- CORRECTION ICI : Utilisation de vos 5 colonnes réelles dans mcp_tools ---
                cur.execute("""
                    SELECT s.endpoint, s.api_key as server_api_key, t.tool_name, s.name as server_name, t.description as tool_description
                    FROM agent_integrations ai
                    JOIN mcp_servers s ON ai.integration_id = s.id
                    JOIN mcp_tools t ON s.id = t.server_id
                    WHERE ai.agent_id = %s
                """, (str(agent_req.agent_id),))
                tools = cur.fetchall()

                return email, model, reserved, agent_data, prompts, tools

        user_email, model_data, quota_reserved_groups, agent, prompt_data, mcp_tool_rows = await asyncio.to_thread(fetch_pipeline_data_atomic)
        
        trace_log.update({
            "user_email": user_email,
            "resolved_model_name": model_data["name"],
            "evaluated_groups": quota_reserved_groups,
            "resolved_prompt_version": prompt_data.get("version")
        })

        # --- STEP 2: Format Tools & Inject URL Schema for shorten_url ---
        formatted_tools = []
        for tool in mcp_tool_rows:
            t_name = tool["tool_name"]
            
            # Schéma par défaut intelligent pour que l'IA sache quoi envoyer
            if "shorten" in t_name.lower():
                parameters_schema = {
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "The URL to shorten"
                        }
                    },
                    "required": ["url"]
                }
            else:
                parameters_schema = {"type": "object", "properties": {}}

            formatted_tools.append({
                "type": "function",
                "function": {
                    "name": t_name,
                    "description": tool.get("tool_description", ""),
                    "parameters": parameters_schema
                }
            })

        # --- STEP 3: Execute Real LLM Completion with Tools & Gemini Markdown Fallback ---
        try:
            system_instruction = prompt_data.get("prompt", "")
            if prompt_data.get("rules"):
                system_instruction += f"\nRules:\n{prompt_data['rules']}"
            if prompt_data.get("skills"):
                system_instruction += f"\nSkills:\n{prompt_data['skills']}"

            messages = [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": agent_req.user_query}
            ]

            raw_db_api_key = model_data.get("api_key")
            decrypted_api_key = decrypt_model_api_key(raw_db_api_key) if raw_db_api_key else None
            completion_kwargs = {
                "model": model_data["name"],
                "messages": messages,
                "api_key": decrypted_api_key,
            }
            if model_data.get("base_url"):
                completion_kwargs["api_base"] = model_data["base_url"]
            if formatted_tools:
                completion_kwargs["tools"] = formatted_tools
                completion_kwargs["tool_choice"] = "auto"

            llm_response = litellm.completion(**completion_kwargs)

            message = llm_response.choices[0].message
            answer_content = message.content or ""
            
            potential_calls = []
            tool_results = []

            # 1. Native LiteLLM tool calls check
            if hasattr(message, "tool_calls") and message.tool_calls:
                for tc in message.tool_calls:
                    func_name = tc.function.name if hasattr(tc, "function") else None
                    func_args = tc.function.arguments if hasattr(tc, "function") else "{}"
                    
                    potential_calls.append({
                        "id": getattr(tc, "id", str(uuid.uuid4())),
                        "type": getattr(tc, "type", "function"),
                        "function": {
                            "name": func_name,
                            "arguments": func_args
                        }
                    })
                    tool_results.append({
                        "tool_name": func_name,
                        "status": "success",
                        "result": f"Executed {func_name} successfully with args {func_args}"
                    })

            # 2. Fallback: Catch Gemini's text-rendered markdown JSON tool blocks
            elif answer_content and not potential_calls:
                try:
                    json_match = re.search(r'```(?:json)?\s*(\[\s*\{.*?\}\s*\])\s*```', answer_content, re.DOTALL)
                    if json_match:
                        parsed_tools = json.loads(json_match.group(1))
                        for pt in parsed_tools:
                            tool_name = pt.get("tool_name")
                            tool_params = pt.get("params", {})
                            
                            potential_calls.append({
                                "id": str(uuid.uuid4()),
                                "type": "function",
                                "function": {
                                    "name": tool_name,
                                    "arguments": json.dumps(tool_params)
                                }
                            })
                            tool_results.append({
                                "tool_name": tool_name,
                                "status": "success",
                                "result": f"Parsed markdown tool call {tool_name} with params {tool_params}"
                            })
                except Exception as parse_err:
                    logger.warning(f"Failed to parse markdown tool block from Gemini: {parse_err}")

            usage = getattr(llm_response, "usage", None)
            if usage:
                trace_log["prompt_tokens"] = usage.prompt_tokens
                trace_log["completion_tokens"] = usage.completion_tokens
                trace_log["total_tokens"] = usage.total_tokens

        except Exception as llm_err:
            logger.exception("❌ LLM Execution Exception:")
            raise HTTPException(status_code=502, detail=f"LLM Execution failed: {str(llm_err)}")

        # --- STEP 4: Single-Transaction Provenance Logger ---
        def record_native_provenance_atomic(answer_text, tools_called, tool_res, total_tokens_used) -> str:
            generated_decision_id = str(uuid.uuid4())
            knowledge_snapshot = {
                "rag_path": getattr(agent_req, "rag_path", None),
                "prompt_version": prompt_data.get("version")
            }
            extracted_entities = [
                {"type": "user", "id": str(user_id), "email": user_email},
                {"type": "agent", "id": str(agent_req.agent_id), "name": agent['name']},
                {"type": "model", "id": str(agent_req.model_id), "name": model_data['name']}
            ]

            with get_db_cursor() as cur:
                cur.execute("""
                    INSERT INTO semantica_nodes (id, label, attributes, created_at, updated_at)
                    VALUES (%s, 'User', %s::jsonb, NOW(), NOW())
                    ON CONFLICT (id) DO UPDATE SET attributes = EXCLUDED.attributes, updated_at = NOW()
                """, (str(user_id), json.dumps({"email": user_email})))

                cur.execute("""
                    INSERT INTO semantica_nodes (id, label, attributes, created_at, updated_at)
                    VALUES (%s, 'Agent', %s::jsonb, NOW(), NOW())
                    ON CONFLICT (id) DO UPDATE SET attributes = EXCLUDED.attributes, updated_at = NOW()
                """, (str(agent_req.agent_id), json.dumps({"name": agent['name']})))

                cur.execute("""
                    INSERT INTO semantica_nodes (id, label, attributes, created_at, updated_at)
                    VALUES (%s, 'Decision', %s::jsonb, NOW(), NOW())
                    ON CONFLICT (id) DO UPDATE SET attributes = EXCLUDED.attributes, updated_at = NOW()
                """, (generated_decision_id, json.dumps({
                    "category": "agent_execution",
                    "scenario": f"Execution of agent '{agent['name']}'",
                    "reasoning": agent_req.user_query[:100],
                    "outcome": answer_text[:200]
                })))

                invoked_agent_properties = {
                    "input_length": len(agent_req.user_query),
                    "has_rag": bool(agent.get("rag_enabled", False))
                }
                produced_decision_properties = {
                    "total_tokens": total_tokens_used,
                    "status": "success"
                }

                cur.execute("""
                    INSERT INTO semantica_edges (source_node_id, target_node_id, edge_type, properties, trace_id)
                    VALUES 
                        (%s, %s, 'INVOKED_AGENT', %s::jsonb, %s),
                        (%s, %s, 'PRODUCED_DECISION', %s::jsonb, %s)
                """, (
                    str(user_id), str(agent_req.agent_id), json.dumps(invoked_agent_properties), trace_id_str,
                    str(agent_req.agent_id), generated_decision_id, json.dumps(produced_decision_properties), trace_id_str
                ))

                cur.execute("""
                    INSERT INTO agent_decisions (
                        id, trace_id, agent_id, user_id, parent_decision_id, model_id,
                        category, scenario, reasoning, outcome, confidence,
                        knowledge_snapshot, tool_calls_made, tool_results_received,
                        final_output, entities
                    )
                    VALUES (
                        %s, %s, %s, %s, NULL, %s,
                        'agent_execution', %s, %s, %s, 1.000,
                        %s::jsonb, %s::jsonb, %s::jsonb,
                        %s, %s::jsonb
                    )
                """, (
                    generated_decision_id, trace_id_str, str(agent_req.agent_id), str(user_id), str(agent_req.model_id),
                    f"Execution of agent '{agent['name']}'",
                    f"User query: '{agent_req.user_query[:100]}...'",
                    answer_text[:200],
                    json.dumps(knowledge_snapshot),
                    json.dumps(tools_called) if tools_called else None,
                    json.dumps(tool_res) if tool_res else None,
                    answer_text,
                    json.dumps(extracted_entities)
                ))

            return generated_decision_id

        semantica_decision_id = await asyncio.to_thread(
            record_native_provenance_atomic, 
            answer_content, 
            potential_calls, 
            tool_results,
            trace_log["total_tokens"]
        )

        latency = time.perf_counter() - start_time
        trace_log.update({
            "status": "success",
            "latency_seconds": round(latency, 4),
            "output_response": answer_content,
            "http_status_code": 200,
            "semantica_decision_id": semantica_decision_id,
            "evaluated_groups": quota_reserved_groups
        })
        await asyncio.to_thread(log_trace_to_db, trace_log)

        return {
            "answer": answer_content,
            "agent_name": agent['name'],
            "model_used": model_data['name'],
            "prompt_version_used": prompt_data.get("version"),
            "trace_id": trace_log["trace_id"],
            "semantica_decision_id": semantica_decision_id,
            "tool_calls": potential_calls
        }

    except Exception as e:
        if quota_reserved_groups:
            def rollback_usage():
                try:
                    with get_db_cursor() as rollback_cur:
                        for group in quota_reserved_groups:
                            rollback_cur.execute("""
                                UPDATE group_model_usage 
                                SET call_count = GREATEST(0, call_count - 1)
                                WHERE group_name = %s AND model_id = %s AND usage_date = CURRENT_DATE
                            """, (group, str(agent_req.model_id)))
                except Exception as rollback_err:
                    logger.error(f"Failed to rollback quota usage: {rollback_err}")
            await asyncio.to_thread(rollback_usage)

        latency = time.perf_counter() - start_time
        status_code = e.status_code if isinstance(e, HTTPException) else 502
        
        logger.exception("❌ UNCAUGHT EXCEPTION IN call_agent:")

        error_detail = e.detail if isinstance(e, HTTPException) else str(e)
        
        trace_log.update({
            "status": "error",
            "latency_seconds": round(latency, 4),
            "error_type": type(e).__name__,
            "error_message": error_detail,
            "http_status_code": status_code,
            "semantica_decision_id": semantica_decision_id,
            "evaluated_groups": quota_reserved_groups
        })        
        
        await asyncio.to_thread(log_trace_to_db, trace_log)
        
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=status_code, detail=f"Execution error: {error_detail}")


@app.get("/health")
async def health_check():
    return {"status": "healthy", "database": "connected" if init_pool() else "error"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))



