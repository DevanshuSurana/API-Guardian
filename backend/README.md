# API Guardian backend

The backend is a FastAPI application that serves the dashboard, analyzes repositories, validates proposed Python fixes, records local finding history, and handles approval-gated GitHub publishing.

For the project overview and full local setup, see the [root README](../README.md).

## Start the app

From the repository root, activate your virtual environment and install the backend dependencies:

```bash
python -m pip install -r backend/requirements-dev.txt
```

Make sure Ollama is running and has the configured model (default: `gemma3:4b`), then start the backend:

```bash
cd backend
OLLAMA_MODEL=gemma3:4b python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

- Dashboard: <http://127.0.0.1:8000/ui>
- OpenAPI docs: <http://127.0.0.1:8000/docs>
- Health: <http://127.0.0.1:8000/health>

## Main API routes

| Route | Purpose |
|---|---|
| `GET /api/repositories/{owner}/{repo}` | Read GitHub repository metadata |
| `POST /api/workspaces/scan/{owner}/{repo}` | Clone a public repository temporarily and list supported source files |
| `POST /api/migrations/analyze` | Scan and audit a repository |
| `POST /api/migrations/fix` | Generate and validate a targeted Python fix proposal |
| `POST /api/migrations/publish/prepare` | Prepare an expiring review of the exact diff; does not publish |
| `POST /api/migrations/publish/approve` | Publish the approved migration branch and draft pull request |
| `GET /api/migrations/publish/status` | Report publishing readiness without exposing credentials |

## Optional GitHub publishing

Publishing is disabled by default. Copy `.env.example` to `.env` and configure:

```dotenv
GITHUB_TOKEN=your_github_token
API_GUARDIAN_ALLOWED_REPOSITORIES=owner/repository
API_GUARDIAN_ENABLE_PUBLISH=true
```

The repository must be explicitly allowlisted, the token must have repository write and pull request permissions, and the user must approve the exact prepared diff in the dashboard. Publishing creates a migration branch and a **draft** pull request; API Guardian does not merge it. Keep `.env` private and never commit a token.

## Local finding history

The backend creates `scan-history.db` in the repository root on first scan. It stores branch-scoped finding metadata and lifecycle status. It does not store source snippets or proposed source code. This file is ignored by Git.

## Tests

From the repository root:

```bash
python -m pytest -q
```

The default pytest configuration excludes tests that require a live Ollama service or external GitHub access.
