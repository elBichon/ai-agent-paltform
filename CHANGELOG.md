# Changelog

All notable changes to this project will be documented in this file.

The project is currently under active development. Items marked as pending are planned work and should not be interpreted as implemented or verified.

This project follows a lightweight changelog format inspired by [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Security

- [ ] Remove insecure default values for production secrets and require explicit configuration.
- [ ] Remove all debug output that could expose decrypted API keys or other credentials.
- [ ] Review encryption key derivation, key storage, rotation, and recovery procedures.
- [ ] Review authentication and authorization across Flask routes and FastAPI endpoints.
- [ ] Verify user, group, agent, integration, model, and API key ownership checks.
- [ ] Harden configurable MCP and external service URLs against SSRF, including DNS rebinding and internal network access.
- [ ] Ensure sensitive values are redacted from application logs and error responses.
- [ ] Add automated security checks and dependency vulnerability scanning.
- [ ] Review production deployment settings, including debug mode, HTTPS, trusted hosts, and proxy configuration.

### API and Gateway

- [ ] Add automated tests for `GET /health` and `POST /v1/call_agent`.
- [ ] Add tests for missing, invalid, expired, and revoked API keys.
- [ ] Review request validation and standardize API error responses.
- [ ] Replace process-local rate limiting with a strategy that works across workers and instances.
- [ ] Make quota checks and usage updates safe under concurrent requests.
- [ ] Implement actual MCP tool execution, with explicit authorization, argument validation, timeouts, and error handling.
- [ ] Review timeout, cancellation, and retry behavior for LLM provider requests.
- [ ] Document the API endpoints, request schemas, response schemas, and authentication requirements.
- [ ] Verify that health checks do not expose sensitive operational details.

### Database

- [ ] Introduce repeatable, versioned database migrations.
- [ ] Review schema initialization and make development setup reproducible.
- [ ] Verify required PostgreSQL extensions and UUID generation support.
- [ ] Add database tests for foreign keys, uniqueness constraints, and transaction rollback.
- [ ] Review indexes and query performance for expected workloads.
- [ ] Document backup, restore, and database upgrade procedures.

### Web Application

- [ ] Audit Flask routes for authentication, authorization, and CSRF protection.
- [ ] Verify secure session cookie settings and session lifecycle behavior.
- [ ] Review registration, login, password handling, and account recovery flows.
- [ ] Test role-based and group-based permissions.
- [ ] Verify that secrets and sensitive information are not exposed through templates or error pages.
- [ ] Confirm all required templates and static assets are included in the repository.
- [ ] Add automated tests for critical user workflows.

### LLM, Integrations, and Provenance

- [ ] Verify model provider credentials are stored and retrieved securely.
- [ ] Add tests for token usage, cost accounting, and model quota enforcement.
- [ ] Verify that recorded agent decisions and provenance relationships are accurate.
- [ ] Review retention and access controls for prompts, model responses, and tool execution records.
- [ ] Add safeguards against prompt injection and unauthorized tool use.
- [ ] Document supported model providers and MCP integration requirements.

### Developer Experience and Documentation

- [ ] Add a complete `.env.example` containing placeholder values only.
- [ ] Add a `.gitignore` covering local environments, secrets, logs, caches, and generated files.
- [ ] Document supported Python and PostgreSQL versions.
- [ ] Add a reproducible local development setup.
- [ ] Add automated linting, formatting, and test execution to CI.
- [ ] Add a CI workflow for dependency and security checks.
- [ ] Document production deployment and configuration.
- [ ] Review `README.md`, `SECURITY.md`, and `CONTRIBUTING.md` for consistency.
- [ ] Verify that all documented commands work from a clean checkout.

### Release Readiness

- [ ] Define the project's versioning and release process.
- [ ] Verify the MIT license file and third-party attribution.
- [ ] Complete a security review before the first production release.
- [ ] Run the full test suite against a clean test database.
- [ ] Document known limitations and unresolved security risks.
- [ ] Create the first tagged release once release criteria are met.

## [0.1.0] - Initial development

### Added

- Initial Flask web application for user-facing functionality.
- Initial FastAPI gateway with health and agent-call endpoints.
- PostgreSQL schema for users, groups, API keys, models, agents, integrations, usage logs, and provenance records.
- Initial LLM integration through LiteLLM.
- Initial API key authentication and request rate limiting.
- Initial agent decision and usage logging.

### Notes

This section describes functionality identified in the initial source review. It does not imply that the features have passed automated tests, security review, or production validation.

The release number and date are provisional. Confirm the actual Git history and release contents before publishing a tagged release.

[Unreleased]: https://github.com/YOUR_USERNAME/YOUR_REPOSITORY/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/YOUR_USERNAME/YOUR_REPOSITORY/releases/tag/v0.1.0