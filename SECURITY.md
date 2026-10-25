# Security Policy

## Supported Versions

Security fixes should be applied to the latest maintained version of this project.

| Version | Supported |
|---|---|
| Latest version on `main` | Yes |
| Older releases | No guarantee |

Until the project establishes a formal release policy, users should assume that only the latest version receives security fixes.

## Reporting a Vulnerability

**Please do not report security vulnerabilities in public GitHub issues.**

If you discover a potential vulnerability, report it privately through one of the following methods:

- Use GitHub's **Private vulnerability reporting** feature, if enabled for this repository.
- If private reporting is unavailable, contact the repository maintainer through the contact information published on the GitHub profile.

Include as much of the following information as possible:

- A description of the vulnerability and its potential impact.
- The affected component, endpoint, or version.
- Steps to reproduce the issue.
- A proof of concept, where safe and appropriate.
- Any suggested mitigation or fix.

Please avoid including real API keys, passwords, personal information, production data, or other sensitive material in your report.

## Response Process

The maintainer will make reasonable efforts to:

1. Acknowledge receipt of the report.
2. Assess the severity and reproducibility of the issue.
3. Investigate and develop a fix or mitigation.
4. Coordinate disclosure with the reporter when practical.
5. Publish a security update and relevant advisory when appropriate.

Response times are not guaranteed until a formal security response commitment is established.

Please allow the maintainer reasonable time to investigate before publicly disclosing an unpatched vulnerability.

## Security Considerations

This project includes a web application, an API gateway, database access, API key handling, and integrations with external services. Deployments should account for the following risks.

### Secrets and credentials

- Never commit API keys, passwords, database URLs, encryption keys, or production secrets.
- Configure secrets through environment variables or a suitable secrets manager.
- Set a strong, unique `FLASK_SECRET_KEY` before deploying the Flask application.
- Do not use development secret defaults in production.
- Remove debug prints and avoid logging decrypted API keys or other credentials.
- Rotate any credential that may have been exposed.

### Authentication and authorization

- Protect authenticated endpoints and administrative functionality.
- Verify that users can access only the agents, integrations, models, and data they are authorized to use.
- Enforce authorization on the server side; hiding a control in the user interface is not sufficient.
- Apply appropriate authentication and authorization checks to both the web application and API gateway.

### API keys and rate limiting

- Store API keys securely and avoid exposing them in responses, logs, or error messages.
- Enforce key ownership, revocation, expiration, and permission checks where applicable.
- Use rate limits that remain effective across multiple workers and application instances.
- Enforce quotas atomically to avoid concurrent requests bypassing usage limits.

### External integrations and SSRF

The application can interact with external services and configurable MCP endpoints.

- Validate endpoint schemes, hostnames, ports, and resolved IP addresses.
- Block access to loopback, private, link-local, and cloud metadata addresses unless explicitly required and safely controlled.
- Revalidate destinations after DNS resolution and guard against DNS rebinding.
- Apply outbound network restrictions and request timeouts.
- Do not assume that an endpoint is safe merely because it was supplied by an authenticated user.

### Database security

- Use parameterized SQL queries.
- Apply least-privilege database credentials.
- Restrict network access to PostgreSQL.
- Back up the database and test recovery procedures.
- Review schema changes and migrations before applying them to production.

### Logging and privacy

- Avoid logging passwords, API keys, authorization headers, and unnecessary personal or confidential data.
- Treat user prompts, model responses, tool arguments, and agent execution traces as potentially sensitive.
- Restrict access to operational logs and define appropriate retention periods.
- Return generic error messages to clients while preserving useful diagnostic information in protected server logs.

### LLM and tool execution

- Treat prompts, retrieved content, model outputs, and external tool results as untrusted input.
- Do not rely on prompt instructions alone to enforce permissions.
- Validate tool arguments and enforce authorization before executing actions.
- Require explicit safeguards for tools that can modify data, access sensitive systems, or trigger external side effects.

## Deployment Recommendations

Before deploying to production:

- [ ] Configure strong production secrets.
- [ ] Disable Flask debug mode.
- [ ] Serve applications over HTTPS behind a properly configured reverse proxy or deployment platform.
- [ ] Restrict database and internal service network access.
- [ ] Review authentication, authorization, and API key handling.
- [ ] Validate outbound requests and MCP endpoints against SSRF.
- [ ] Configure rate limits and quotas for multi-worker deployments.
- [ ] Review sensitive-data logging and retention.
- [ ] Keep dependencies updated and scan for known vulnerabilities.
- [ ] Test backup, recovery, and credential rotation procedures.

## Scope

This policy covers security vulnerabilities in this project's code, configuration, and documented deployment patterns.

Third-party services, LLM providers, hosting platforms, and user-managed infrastructure may have separate security reporting procedures.

## Responsible Use

Please conduct security testing only on systems you own or have explicit permission to test. Do not access, modify, or disclose other users' data during testing.

Thank you for helping keep this project secure.