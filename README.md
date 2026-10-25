# AI Agent Platform

An open-source Python platform for managing and executing AI agents, integrating tools and MCP servers, enforcing model usage limits, and tracking agent execution provenance.

The project combines a web application with a FastAPI gateway and PostgreSQL database to support agent management, model access, API authentication, usage tracking, and decision history.

> **Status:** Under development. Review the security notes and verify the complete project structure before deploying to production.
> See [`https://github.com/elBichon/ai-agent-paltform/blob/main/src/test.py`](test.py) for an example of how to use the platform as a consumer.

### Coming features

- [ ] Openrouter based pricing
- [ ] Coest estimation and cost based segmentation
- [ ] Agent based prompt evaluation and optimisation (adding the related sql)
- [ ] Dynamic model suggestions based on prompt system

## Features

### Agent management
- Create and manage AI agents.
- Configure agent prompts, rules, skills, and prompt versions.
- Pause agents and configure public or private status.
- Associate agents with integrations and tools.
- Support optional RAG-related configuration.

### API gateway
- Expose an API endpoint for executing agents.
- Authenticate requests using API keys.
- Apply per-key request rate limiting.
- Resolve agents, models, prompt versions, and user access.
- Record execution results, latency, errors, and token usage.

### Model management and quotas
- Integrate language models through LiteLLM.
- Configure model endpoints and credentials.
- Apply group-based model constraints.
- Track daily model call counts.
- Enforce configured daily call limits.

### MCP and integrations
- Store MCP server configurations and tool definitions.
- Associate integrations with agents.
- Provide tool definitions to language models during execution.

### Execution provenance and analytics
- Store API gateway execution logs.
- Track token usage and estimated costs.
- Record agent decisions and execution metadata.
- Represent relationships between users, agents, decisions, and traces using Semantica nodes and edges.
- Search selected decision fields using PostgreSQL trigram indexes.

### User access and permissions
- Support users, groups, and access levels.
- Store API keys associated with users.
- Manage access to agents and integrations.

## Architecture

The project includes the following main components:

- **Web application:** Flask-based interface for managing platform resources.
- **API gateway:** FastAPI application in `api.py` for authenticated agent execution.
- **Database:** PostgreSQL, with tables for users, agents, models, integrations, quotas, execution logs, and provenance.
- **LLM integration:** LiteLLM for model completion requests.
- **Tool integration:** MCP server and tool configuration stored in PostgreSQL.
- **Provenance layer:** `semantica_nodes`, `semantica_edges`, and `agent_decisions` tables for recording execution context and relationships.

## Tech stack

- Python
- Flask
- FastAPI
- PostgreSQL
- Psycopg2
- Pydantic
- LiteLLM
- Flask-WTF
- Cryptography
- Requests
- Uvicorn
- Python-dotenv

## Requirements

You will need:

- Python 3.10 or later, subject to dependency compatibility.
- PostgreSQL.
- Git.
- `pip`.

The database user must be able to connect to the target database and create the required tables, indexes, and PostgreSQL extension during initial setup.

## Repository structure


```text
ai-agent-platform/
├── app.py
├── api.py
├── schema.sql
├── requirements.txt
├── LICENSE
├── README.md
├── CONTRIBUTING.md
├── SECURITY.md
├── CHANGELOG.md
├── templates/
├── static/
```

This is a suggested structure, not a complete inventory. Include all templates, static files, and other modules imported by your actual application. Add a `tests/` directory when tests are available.

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/elBichon/ai-agent-paltform.git
cd ai-agent-platform
```

### 2. Create a virtual environment

```bash
python -m venv .venv
```

Activate it on Linux or macOS:

```bash
source .venv/bin/activate
```

On Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

### 3. Install dependencies

Once `requirements.txt` is configured:

```bash
pip install -r requirements.txt
```

Ensure that the dependency list covers both the Flask web application and the FastAPI gateway.

### 4. Configure environment variables

Create a local `.env` file for development, or configure the variables through your deployment environment.

Example:

```dotenv
DATABASE_URL=postgresql://username:password@localhost:5432/ai_agent_platform
FLASK_SECRET_KEY=replace_with_a_secure_random_secret
PORT=8000
```

Generate a strong random secret with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

The current code uses `DATABASE_URL` for PostgreSQL and reads `FLASK_SECRET_KEY` for encryption-key derivation. `PORT` controls the listening port of each application's entry point, so configure it appropriately when running the web application and API gateway separately.


### 5. Create the PostgreSQL database

Create a database, for example:

```sql
CREATE DATABASE ai_agent_platform;
```

Connect to that database and execute the schema:

```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f schema.sql
```

The schema creates the application's tables and indexes, including:

- `users`, `users_email`, `user_level`, and `user_groups`
- `agents`, `agent_integrations`, and `prompt_system_versions`
- `models`, `model_constraints`, and `group_model_usage`
- `mcp_servers`, `mcp_tools`, and `integrations`
- `api_keys` and `api_gateway_logs`
- `semantica_nodes`, `semantica_edges`, and `agent_decisions`

The schema also enables PostgreSQL's `pg_trgm` extension for trigram-based text search and uses `gen_random_uuid()` for UUID defaults. Confirm that your PostgreSQL installation supports these features and that the database role has the necessary permissions.

**Note:** The schema uses `CREATE TABLE` and `CREATE INDEX` statements that are not consistently guarded with `IF NOT EXISTS`. Treat it as an initial schema for a fresh database; do not assume it can safely be applied repeatedly or used as a database migration system.

## Running the applications

### Start the web application

The Flask application entry point is `app.py` in the current project layout:

```bash
python app.py
```

Check the application configuration for its actual listening port and required templates.

### Start the API gateway

Run the FastAPI application with Uvicorn:

```bash
uvicorn api:app --host 0.0.0.0 --port 8000
```

For local development, the API health endpoint is:

```text
http://127.0.0.1:8000/health
```

The `/health` endpoint reports whether the database connection pool can be initialized. It should not be interpreted as a comprehensive readiness check of every application dependency.

For production, run the API behind an appropriately configured reverse proxy or hosting platform, with debug features disabled and secrets managed securely.

## API usage

### Health check

```http
GET /health
```

Example response:

```json
{
  "status": "healthy",
  "database": "connected"
}
```

The response's `database` field indicates whether the connection pool was initialized successfully.

### Execute an agent

```http
POST /v1/call_agent
X-API-Key: YOUR_API_KEY
Content-Type: application/json
```

Example request body:

```json
{
  "agent_id": "YOUR_AGENT_UUID",
  "user_query": "Summarize the latest project updates.",
  "model_id": "YOUR_MODEL_UUID",
  "rag_path": null,
  "prompt_version": null
}
```

Replace the example identifiers with valid UUIDs from your database. The API key must belong to a user who has access to the requested agent and satisfies the configured model access constraints.

The `rag_path` field is accepted by the request model and recorded in the knowledge snapshot. The current code does not itself implement retrieval from that path.

### Example response

A successful request returns an object containing fields similar to:

```json
{
  "answer": "Example generated response.",
  "agent_name": "Example Agent",
  "model_used": "configured-model-name",
  "prompt_version_used": 1,
  "trace_id": "TRACE_UUID",
  "semantica_decision_id": "DECISION_UUID",
  "tool_calls": []
}
```

The values above are illustrative. Actual output depends on the configured agent, model provider, prompt, and execution result.

### Authentication and rate limiting

The gateway reads API keys from the `X-API-Key` request header and validates them against the `api_keys` table.

The current implementation applies a limit of 60 requests per API key per rolling 60-second window using in-memory state. This limit is process-local and resets when the process restarts; it is not a distributed rate limiter.

## Configuration notes

- Configure a valid PostgreSQL connection through `DATABASE_URL`.
- Configure model records with the appropriate model name, base URL, and encrypted API key.
- Ensure that encryption and decryption use the same secure key-management configuration.
- Create the necessary users, groups, agents, prompt versions, model constraints, and API keys before testing the execution endpoint.
- Configure MCP servers and tool records consistently with the integration relationships expected by the application.
- Review database permissions and retention requirements for execution logs and provenance records.

## Security

This application processes user queries, model credentials, API keys, and execution logs. A security review is required before production deployment.

Important items to address include:

- **Development secret fallback:** The code uses a fallback value when `FLASK_SECRET_KEY` is not configured. Remove this fallback and require a strong secret in deployed environments.
- **Encryption key management:** The current API derives a Fernet key from the application secret and a fixed salt. Establish a secure, versioned key-management strategy before storing real model credentials.
- **Credential exposure:** The API code currently prints the decrypted model API key. Remove this output immediately; secrets must never be printed to logs or standard output.
- **Authorization:** Verify that users can only invoke agents, models, integrations, and tools they are authorized to use. In particular, review whether model access is properly scoped to the requesting user.
- **Tool execution:** The current code constructs tool-call metadata and records it, but does not implement actual execution of the returned tool calls in this endpoint. Validate any future tool execution against an explicit allowlist and authorization policy.
- **Rate limiting:** Replace in-memory rate limiting with a shared backend if the service runs across multiple workers or instances.
- **Quota enforcement:** Review concurrent quota reservations and ensure that usage is updated atomically under concurrent requests.
- **Sensitive logging:** Execution logs may contain full user queries and generated responses. Define access controls, retention periods, and redaction rules.
- **Error responses:** Avoid exposing internal exception details or provider errors to API clients.
- **Network security:** Validate model and integration endpoints to prevent server-side request forgery and access to internal network resources.
- **Transport security:** Use HTTPS for externally accessible services and protect API keys in transit.
- **Dependencies:** Review and update dependencies regularly, and run security checks before releases.

These are observations from the supplied code, not a complete security audit. Do not use the application with production secrets or sensitive user data until the relevant issues have been addressed.

Please report vulnerabilities according to the instructions in `SECURITY.md`, rather than posting sensitive exploit details publicly.

## Testing

A complete test suite was not included in the supplied files. Tests should be added for at least:

- API key validation and authorization.
- Agent ownership and access checks.
- Model constraints and quota enforcement.
- PostgreSQL transaction handling.
- Prompt version selection.
- LLM provider failures and timeouts.
- Tool-call parsing and execution boundaries.
- Execution logging and provenance persistence.
- Error handling and rate limiting.

Document the test command here once the project has a working test configuration.

## Contributing

Contributions are welcome.

1. Fork the repository.
2. Create a branch for your change.
3. Keep changes focused and document relevant behavior.
4. Add or update tests where practical.
5. Run the available checks.
6. Submit a pull request with a clear description of the change.

Please do not commit secrets, API keys, database dumps, private user data, or production logs.

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for contribution guidelines.

## Reporting security issues

See [`SECURITY.md`](SECURITY.md) for instructions on reporting security vulnerabilities.

## License

This project is intended to be released under the MIT License. See [`LICENSE`](https://github.com/elBichon/ai-agent-paltform?tab=MIT-1-ov-file) for the full license text.

Before publishing, replace any copyright-holder placeholder in the license and confirm that you have the rights to release all included code and assets under MIT.
