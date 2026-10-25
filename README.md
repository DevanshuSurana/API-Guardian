# API Guardian

API Guardian scans a GitHub repository for API usage and compatibility risks, explains potential problems, and proposes code fixes for review. It uses a local Ollama model for analysis. Publishing a branch and draft pull request requires an explicit approval of the prepared diff.

## Repository layout

```text
ai_agent/          Local-model audit and repair agents
backend/           FastAPI service, dashboard, GitHub integration, and backend tests
datasets/          Versioned API-change and migration evaluation fixtures
mlops/             Evaluation metrics, DVC pipeline, and MLflow tracking
tests/             Root-level MLOps tests
README_MEMBER3.md  Member 3 guide to evaluation and MLOps
```

The backend serves the interactive dashboard at `/ui` and the API documentation at `/docs`. See [backend/README.md](backend/README.md) for API, GitHub publishing, and backend details, and [ai_agent/README.md](ai_agent/README.md) for the agent interface.

## Requirements

- Python `>=3.13,<3.15`
- Git
- [Ollama](https://ollama.com/) running locally with `gemma3:4b`

## Run locally in VS Code

Open the repository root or `API-Guardian.code-workspace` in VS Code. From the integrated terminal:

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -r backend/requirements-dev.txt
python -m pip install -e .
ollama pull gemma3:4b
```

If you already have a virtual environment, activate it and skip the creation command. Start the backend:

```bash
cd backend
OLLAMA_MODEL=gemma3:4b ../.venv/bin/python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Then open <http://127.0.0.1:8000/ui>. On Windows, use the activation and launch commands in [backend/README.md](backend/README.md).

## Local configuration

Copy `backend/.env.example` to `backend/.env` only if `backend/.env` does not already exist. Add a GitHub token there only when you need authenticated publishing. `.env` files are ignored by Git; never commit or share the token. Publishing remains disabled in the example until you explicitly enable it for an allowed repository.

## Evaluation

The evaluation fixtures are synthetic smoke-test data; their baseline values are not measurements of live agent performance. Run the DVC evaluation from the repository root with:

```bash
dvc repro
```

See [README_MEMBER3.md](README_MEMBER3.md) for the evaluation datasets, metrics, and MLflow/DVC workflow.
