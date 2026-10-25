# Contributing

Thank you for your interest in contributing to this project!

Contributions of all kinds are welcome, including bug fixes, security improvements, documentation, tests, user interface enhancements, API improvements, and new integrations.

This project combines a Flask web application, a FastAPI gateway, PostgreSQL, LLM integrations, and MCP-related functionality. Contributions should preserve maintainability, security, and compatibility across these components.

## Ways to Contribute

You can contribute by:

- Reporting reproducible bugs.
- Proposing features or architectural improvements.
- Improving documentation and installation instructions.
- Adding or improving automated tests.
- Fixing security vulnerabilities through the process described in `SECURITY.md`.
- Improving API authentication, authorization, quotas, and observability.
- Adding integrations with appropriate validation and access controls.

For substantial changes, open an issue or discussion first so that the proposed design can be discussed before significant work begins.

## Getting Started

### 1. Fork and clone the repository

Fork the project on GitHub, then clone your fork:

```bash
git clone https://github.com/YOUR_USERNAME/YOUR_REPOSITORY.git
cd YOUR_REPOSITORY
```

Replace the placeholders with your GitHub username and repository name.

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

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Check for dependency conflicts:

```bash
pip check
```

### 4. Configure environment variables

Create a local `.env` file using the project's documented environment variables. Never commit this file.

At minimum, configure the database connection and a strong Flask secret:

```dotenv
DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/DATABASE
FLASK_SECRET_KEY=replace-with-a-strong-random-secret
```

Configure any additional provider credentials required by the functionality you are testing.

Use development or test credentials only. Do not use production secrets or real user data.

### 5. Initialize the database

Ensure PostgreSQL is installed, running, and accessible.

Apply the schema using the command documented by the project:

```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f schema.sql
```

On Windows, use the equivalent command for your shell and database setup.

**Note:** The current schema may not be safe to apply repeatedly. Use a disposable development database until repeatable migrations and a test database setup are available.

### 6. Run the applications

Start the Flask web application:

```bash
python app.py
```

Start the FastAPI gateway in a separate terminal:

```bash
uvicorn api:app --host 127.0.0.1 --port 8000 --reload
```

Use the documented web application port and API configuration for your local environment. Avoid exposing development servers to public networks.

## Development Guidelines

### Code quality

- Follow the conventions of the existing codebase.
- Prefer small, focused changes over unrelated refactoring.
- Use descriptive names and clear function boundaries.
- Handle errors explicitly and avoid exposing internal details to clients.
- Remove temporary debugging statements before submitting changes.
- Keep comments and documentation accurate as behavior changes.

### Security

- Never commit secrets, credentials, tokens, or real user data.
- Never print or log decrypted API keys.
- Use parameterized database queries.
- Validate and authorize every sensitive operation on the server.
- Treat external URLs, MCP endpoints, model outputs, and tool arguments as untrusted.
- Add appropriate timeouts and validation to network requests.
- Avoid introducing new dependencies without a clear reason.
- Report vulnerabilities privately according to `SECURITY.md` rather than opening a public issue.

### Database changes

- Explain schema changes and their impact.
- Include migrations or upgrade instructions when appropriate.
- Preserve data integrity and foreign-key constraints.
- Consider concurrent requests and transaction boundaries when modifying quotas, usage tracking, or API key state.
- Test changes against a disposable PostgreSQL database.

### API changes

- Document new endpoints, parameters, responses, and error cases.
- Preserve compatibility where practical, or clearly document breaking changes.
- Validate request data and enforce authorization.
- Avoid returning secrets, sensitive database details, or stack traces.
- Include tests for authentication, invalid inputs, and permission failures where relevant.

### Tests

Add or update tests for behavior affected by your changes.

Where applicable, test:

- Successful and unsuccessful authentication.
- Authorization boundaries between users and groups.
- Invalid input and malformed requests.
- API key revocation and access control.
- Quota enforcement under concurrent requests.
- Database errors and transaction rollback.
- External endpoint validation and timeout behavior.
- Logging that must not contain secrets.
- Regression cases for previously reported bugs.

Do not claim a test has passed unless you have run it.

## Before Submitting a Pull Request

- [ ] The change has a clear purpose and scope.
- [ ] Relevant tests have been added or updated.
- [ ] Tests have been run locally, and results are reported accurately.
- [ ] No secrets, credentials, or sensitive user data are included.
- [ ] Documentation and configuration examples are updated.
- [ ] Database changes include appropriate migration or setup instructions.
- [ ] Security and authorization implications have been considered.
- [ ] Temporary debugging code has been removed.
- [ ] The pull request describes the change, its motivation, and any known limitations.

## Pull Request Process

1. Create a feature branch:

   ```bash
   git checkout -b feature/short-description
   ```

2. Make focused changes and commit them with clear messages.

3. Push the branch to your fork:

   ```bash
   git push origin feature/short-description
   ```

4. Open a pull request against the project's `main` branch.

5. Describe what changed, why it changed, how it was tested, and any risks or follow-up work.

6. Respond constructively to review feedback and update the pull request as needed.

Pull requests may be revised, deferred, or declined if they introduce security risks, break documented behavior, lack sufficient testing, or fall outside the project's goals.

## Commit Messages

Use short, descriptive commit messages. For example:

```text
fix: prevent API key exposure in logs
feat: add integration permission checks
test: cover API authentication failures
docs: clarify local database setup
```

These prefixes are recommendations rather than a mandatory commit format.

## Dependencies

When adding or updating dependencies:

- Explain why the dependency is needed.
- Check compatibility with the supported Python version and existing packages.
- Pin versions where appropriate for reproducible deployments.
- Check for known vulnerabilities and license compatibility.
- Avoid dependencies that duplicate existing functionality without a clear benefit.

## License

By submitting a contribution, you agree that your contribution may be distributed under the repository's MIT License, subject to the applicable terms of that license.

If you add third-party code or assets, ensure that their licenses are compatible and include required attribution.

## Code of Conduct

Please be respectful, constructive, and inclusive in issues, discussions, reviews, and other project interactions.

Harassment, personal attacks, discriminatory behavior, and deliberate disruption are not acceptable.

The maintainer may moderate contributions and interactions to keep the project welcoming and productive.

Thank you for helping improve the project!