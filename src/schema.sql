CREATE SCHEMA IF NOT EXISTS "public";

-- Enable pg_trgm extension for fast ILIKE and fuzzy text search across agent decisions
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- ============================================================================
-- 1. AUTH & CORE USER TABLES
-- ============================================================================

CREATE TABLE IF NOT EXISTS "users" (
    "id" uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    "google_id" varchar(255) CONSTRAINT "users_google_id_key" UNIQUE,
    "email" varchar(255) NOT NULL CONSTRAINT "users_email_key" UNIQUE,
    "name" varchar(255),
    "creation_date" timestamp with time zone DEFAULT now() NOT NULL
);


CREATE TABLE "users_email" (
    "id" uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    "email" varchar(255) NOT NULL CONSTRAINT "users_email_email_key" UNIQUE REFERENCES "users"("email") ON DELETE CASCADE,
    "password_hash" text NOT NULL,
    "created_at" timestamp with time zone DEFAULT now() NOT NULL
);

CREATE TABLE "user_level" (
    "id" uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    "user_email" varchar(255) NOT NULL CONSTRAINT "user_level_user_email_key" UNIQUE REFERENCES "users"("email") ON DELETE CASCADE,
    "groups" text[],
    "access_level" varchar(20) NOT NULL,
    "created_at" timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT "user_level_access_level_check" CHECK (((access_level)::text = ANY ((ARRAY['user'::character varying, 'editor'::character varying, 'admin'::character varying])::text[])))
);

CREATE TABLE "groups" (
    "id" uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    "name" varchar(255) NOT NULL CONSTRAINT "groups_name_key" UNIQUE,
    "created_at" timestamp with time zone DEFAULT now() NOT NULL
);

CREATE TABLE "user_groups" (
    "user_email" varchar(255) NOT NULL,
    "group_name" varchar(255) NOT NULL,
    CONSTRAINT "user_groups_pkey" PRIMARY KEY("user_email", "group_name")
);

CREATE TABLE "api_keys" (
    "id" uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    "user_id" uuid NOT NULL,
    "key_value" varchar(255) NOT NULL CONSTRAINT "api_keys_key_value_key" UNIQUE,
    "name" varchar(255),
    "created_at" timestamp with time zone DEFAULT now() NOT NULL
);

-- ============================================================================
-- 2. MODELS & CONSTRAINTS
-- ============================================================================

CREATE TABLE "models" (
    "id" uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    "name" varchar(255) NOT NULL CONSTRAINT "models_name_key" UNIQUE,
    "base_url" text NOT NULL,
    "api_key" text NOT NULL,
    "created_at" timestamp with time zone DEFAULT now() NOT NULL
);

CREATE TABLE "model_constraints" (
    "id" uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    "group_name" varchar(255) NOT NULL,
    "model_id" uuid NOT NULL,
    "max_calls" integer,
    "max_amount" numeric(10, 2),
    "created_at" timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT "model_constraints_group_model_unique" UNIQUE("group_name", "model_id")
);

CREATE TABLE "group_model_usage" (
    "group_name" varchar(255) NOT NULL,
    "model_id" uuid NOT NULL,
    "usage_date" date DEFAULT CURRENT_DATE NOT NULL,
    "call_count" integer DEFAULT 0 NOT NULL,
    CONSTRAINT "group_model_usage_pkey" PRIMARY KEY("group_name", "model_id", "usage_date")
);

-- ============================================================================
-- 3. MCP & INTEGRATIONS
-- ============================================================================

CREATE TABLE "mcp_servers" (
    "id" uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    "name" varchar(255) NOT NULL,
    "endpoint" text NOT NULL,
    "api_key" text, 
    "description" text NOT NULL,
    "creator_user_id" uuid NOT NULL REFERENCES "users"("id") ON DELETE CASCADE,
    "status" varchar(20) DEFAULT 'private' NOT NULL,
    "tags" text[], 
    "created_at" timestamp with time zone DEFAULT now() NOT NULL
);

CREATE TABLE "mcp_tools" (
    "id" uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    "server_id" uuid REFERENCES "mcp_servers"("id") ON DELETE CASCADE,
    "tool_name" varchar(255) NOT NULL, 
    "description" text NOT NULL,         
    "created_at" timestamp with time zone DEFAULT now() NOT NULL
);

CREATE TABLE "integrations" (
    "id" uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    "creation_date" timestamp with time zone DEFAULT now() NOT NULL,
    "creator_user_id" uuid NOT NULL REFERENCES "users"("id") ON DELETE CASCADE,
    "name" varchar(255) NOT NULL,
    "description" text,
    "endpoint" text NOT NULL,
    "type" varchar(10) NOT NULL,
    "status" varchar(20) NOT NULL,
    "security_status" varchar(20),
    "tags" text[],
    CONSTRAINT "integrations_status_check" CHECK (((status)::text = ANY ((ARRAY['public'::character varying, 'private'::character varying])::text[]))),
    CONSTRAINT "integrations_type_check" CHECK (((type)::text = ANY ((ARRAY['tool'::character varying, 'mcp'::character varying])::text[])))
);

CREATE TABLE "user_integration_suite" (
    "user_id" uuid NOT NULL,
    "integration_id" uuid NOT NULL,
    "added_at" timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT "user_integration_suite_pkey" PRIMARY KEY("user_id", "integration_id")
);

-- ============================================================================
-- 4. AGENTS
-- ============================================================================

CREATE TABLE "agents" (
    "id" uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    "name" varchar(255) NOT NULL,
    "description" text,
    "creation_date" timestamp with time zone DEFAULT now() NOT NULL,
    "creator_user_id" uuid NOT NULL REFERENCES "users"("id") ON DELETE CASCADE,
    "status" varchar(20) NOT NULL,
    "rag_enabled" boolean DEFAULT false NOT NULL,
    "paused" boolean DEFAULT false NOT NULL,
    "tags" text[],
    CONSTRAINT "agents_status_check" CHECK (((status)::text = ANY ((ARRAY['public'::character varying, 'private'::character varying])::text[])))
);

CREATE TABLE "agent_integrations" (
    "agent_id" uuid NOT NULL REFERENCES "agents"("id") ON DELETE CASCADE,
    "integration_id" uuid NOT NULL REFERENCES "integrations"("id") ON DELETE CASCADE,
    CONSTRAINT "agent_integrations_pkey" PRIMARY KEY("agent_id", "integration_id")
);

CREATE TABLE "prompt_system_versions" (
    "id" uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    "agent_id" uuid NOT NULL REFERENCES "agents"("id") ON DELETE CASCADE,
    "creation_date" timestamp with time zone DEFAULT now() NOT NULL,
    "version" integer NOT NULL,
    "prompt" text NOT NULL,
    "rules" text,
    "skills" text,
    CONSTRAINT "prompt_system_versions_agent_version_unique" UNIQUE("agent_id", "version")
);

CREATE TABLE "user_agent_suite" (
    "user_id" uuid NOT NULL REFERENCES "users"("id") ON DELETE CASCADE,
    "agent_id" uuid NOT NULL REFERENCES "agents"("id") ON DELETE CASCADE,
    "added_at" timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT "user_agent_suite_pkey" PRIMARY KEY("user_id", "agent_id")
);

-- ============================================================================
-- 5. API GATEWAY LOGS
-- ============================================================================

CREATE TABLE "api_gateway_logs" (
    "trace_id" uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    "timestamp" timestamp with time zone DEFAULT now() NOT NULL,
    "user_id" uuid REFERENCES "users"("id") ON DELETE SET NULL,
    "agent_id" uuid REFERENCES "agents"("id") ON DELETE CASCADE,
    "requested_model_id" uuid REFERENCES "models"("id") ON DELETE SET NULL,
    "input_query_length" integer NOT NULL,
    "input_query" text NOT NULL,
    "user_email" varchar(255) NOT NULL,
    "resolved_model_name" varchar(255) NOT NULL,
    "evaluated_groups" text[] DEFAULT '{}'::text[], 
    "status" varchar(20) NOT NULL,
    "latency_seconds" numeric(8, 4) NOT NULL,
    "output_response" text,
    "error_type" varchar(255),
    "error_message" text,
    "http_status_code" integer,
    "prompt_tokens" integer DEFAULT 0 NOT NULL,
    "completion_tokens" integer DEFAULT 0 NOT NULL,
    "total_tokens" integer DEFAULT 0 NOT NULL,
    "estimated_cost_usd" numeric(12, 6) DEFAULT 0.0 NOT NULL
);

-- ============================================================================
-- 6. SEMANTICA PAYLOAD TABLES (Graph & Decision Provenance)
-- ============================================================================

CREATE TABLE "semantica_nodes" (
    "id" varchar(255) PRIMARY KEY, 
    "label" varchar(255) NOT NULL, 
    "attributes" jsonb DEFAULT '{}'::jsonb NOT NULL,
    "created_at" timestamp with time zone DEFAULT now() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT now() NOT NULL
);

CREATE TABLE "semantica_edges" (
    "id" uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    "source_node_id" varchar(255) NOT NULL REFERENCES "semantica_nodes"("id") ON DELETE CASCADE,
    "target_node_id" varchar(255) NOT NULL REFERENCES "semantica_nodes"("id") ON DELETE CASCADE,
    "edge_type" varchar(255) NOT NULL, 
    "properties" jsonb DEFAULT '{}'::jsonb NOT NULL,
    "trace_id" uuid REFERENCES "api_gateway_logs"("trace_id") ON DELETE SET NULL,
    "created_at" timestamp with time zone DEFAULT now() NOT NULL
);

CREATE TABLE "agent_decisions" (
    "id" uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    "trace_id" uuid REFERENCES "api_gateway_logs"("trace_id") ON DELETE SET NULL,
    "agent_id" uuid NOT NULL REFERENCES "agents"("id") ON DELETE CASCADE,
    "user_id" uuid REFERENCES "users"("id") ON DELETE SET NULL,
    "parent_decision_id" uuid REFERENCES "agent_decisions"("id") ON DELETE SET NULL,
    "model_id" uuid REFERENCES "models"("id") ON DELETE SET NULL,
    
    "category" varchar(100) DEFAULT 'agent_execution' NOT NULL,
    "scenario" text,
    "reasoning" text,
    "outcome" text,
    "confidence" numeric(4, 3) DEFAULT 1.000 NOT NULL,
    
    "knowledge_snapshot" jsonb NOT NULL, 
    "tool_calls_made" jsonb,            
    "tool_results_received" jsonb,      
    "final_output" text NOT NULL,
    "entities" jsonb DEFAULT '[]'::jsonb NOT NULL,
    "created_at" timestamp with time zone DEFAULT now() NOT NULL
);

-- ============================================================================
-- 7. INDEXES & PERFORMANCE OPTIMIZATIONS
-- ============================================================================

-- Semantica Standard Indexes
CREATE INDEX "idx_semantica_nodes_label" ON "semantica_nodes"("label");
CREATE INDEX "idx_semantica_nodes_attributes" ON "semantica_nodes" USING gin("attributes");

CREATE INDEX "idx_semantica_edges_source" ON "semantica_edges"("source_node_id");
CREATE INDEX "idx_semantica_edges_target" ON "semantica_edges"("target_node_id");
CREATE INDEX "idx_semantica_edges_type" ON "semantica_edges"("edge_type");
CREATE INDEX "idx_semantica_edges_trace" ON "semantica_edges"("trace_id");

CREATE INDEX "idx_decisions_parent" ON "agent_decisions"("parent_decision_id");
CREATE INDEX "idx_decisions_agent" ON "agent_decisions"("agent_id");
CREATE INDEX "idx_decisions_trace" ON "agent_decisions"("trace_id");
CREATE INDEX "idx_decisions_entities" ON "agent_decisions" USING gin("entities");

-- Trigram Indexes for Fast Full-Text ILIKE Search
CREATE INDEX "idx_decisions_reasoning_trgm" ON "agent_decisions" USING gin("reasoning" gin_trgm_ops);
CREATE INDEX "idx_decisions_outcome_trgm" ON "agent_decisions" USING gin("outcome" gin_trgm_ops);
CREATE INDEX "idx_decisions_scenario_trgm" ON "agent_decisions" USING gin("scenario" gin_trgm_ops);
CREATE INDEX "idx_semantica_nodes_label_trgm" ON "semantica_nodes" USING gin("label" gin_trgm_ops);

-- Core System Indexes
CREATE INDEX "idx_logs_agent_lookup" ON "api_gateway_logs" ("agent_id", "timestamp" DESC);
CREATE INDEX "idx_agents_creator" ON "agents" ("creator_user_id");
CREATE INDEX "idx_agents_status" ON "agents" ("status");
CREATE INDEX "idx_api_keys_user" ON "api_keys" ("user_id");
CREATE INDEX "idx_api_keys_value" ON "api_keys" ("key_value");
CREATE INDEX "idx_group_model_usage_lookup" ON "group_model_usage" ("group_name", "model_id", "usage_date");
CREATE INDEX "idx_integrations_creator" ON "integrations" ("creator_user_id");
CREATE INDEX "idx_integrations_security_status" ON "integrations" ("security_status");
CREATE INDEX "idx_integrations_status" ON "integrations" ("status");
CREATE INDEX "idx_integrations_type" ON "integrations" ("type");
CREATE INDEX "idx_prompt_agent" ON "prompt_system_versions" ("agent_id");
CREATE INDEX "idx_suite_user" ON "user_agent_suite" ("user_id");
CREATE INDEX "idx_suite_int_user" ON "user_integration_suite" ("user_id");
CREATE INDEX "idx_user_level_email" ON "user_level" ("user_email");

-- Foreign Key Constraints
ALTER TABLE "api_keys" ADD CONSTRAINT "fk_api_keys_user" FOREIGN KEY ("user_id") REFERENCES "users"("id") ON DELETE CASCADE;
ALTER TABLE "group_model_usage" ADD CONSTRAINT "fk_usage_group" FOREIGN KEY ("group_name") REFERENCES "groups"("name") ON DELETE CASCADE;
ALTER TABLE "group_model_usage" ADD CONSTRAINT "fk_usage_model" FOREIGN KEY ("model_id") REFERENCES "models"("id") ON DELETE CASCADE;
ALTER TABLE "model_constraints" ADD CONSTRAINT "fk_constraints_group" FOREIGN KEY ("group_name") REFERENCES "groups"("name") ON DELETE CASCADE;
ALTER TABLE "model_constraints" ADD CONSTRAINT "fk_constraints_model" FOREIGN KEY ("model_id") REFERENCES "models"("id") ON DELETE CASCADE;
ALTER TABLE "user_groups" ADD CONSTRAINT "fk_user_groups_email" FOREIGN KEY ("user_email") REFERENCES "user_level"("user_email") ON DELETE CASCADE;
ALTER TABLE "user_groups" ADD CONSTRAINT "fk_user_groups_name" FOREIGN KEY ("group_name") REFERENCES "groups"("name") ON DELETE CASCADE;
ALTER TABLE "user_integration_suite" ADD CONSTRAINT "fk_suite_int" FOREIGN KEY ("integration_id") REFERENCES "integrations"("id") ON DELETE CASCADE;
ALTER TABLE "user_integration_suite" ADD CONSTRAINT "fk_suite_user" FOREIGN KEY ("user_id") REFERENCES "users"("id") ON DELETE CASCADE;