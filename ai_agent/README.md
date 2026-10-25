# API Guardian — Member 1: AI Agent

This module implements the AI agent interface shared with the API Guardian team.

```python
from api_agent import generate_migration

result = generate_migration(changelog, source_code)
```

The agent analyzes an API changelog and source code, identifies potential breaking changes and affected usages, and proposes a migration patch.

**The agent does not edit project files, execute generated code, run tests on the proposed patch, or create pull requests.** These actions belong in the backend integration and should use an appropriately isolated sandbox.

## 1. Requirements

- Python 3.10 or newer
- [Ollama](https://ollama.com/) installed and running
- The `gemma3:4b` model downloaded, or another compatible model
- No internet connection is required for model inference after the model is downloaded

## 2. Setup

### macOS / Linux

From the project directory:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Install Ollama from https://ollama.com/ if it is not already installed.

Download the default model:

```bash
ollama pull gemma3:4b
```

Make sure the Ollama service is running. Depending on your installation, you may need to open the Ollama app or run:

```bash
ollama serve
```

If Ollama is already running, do not start a second instance.

### Windows PowerShell

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Install Ollama from https://ollama.com/, then run:

```powershell
ollama pull gemma3:4b
```

Make sure the Ollama service is running before starting the agent.

## 3. Configure the model (optional)

The default configuration is:

- Ollama host: `http://localhost:11434`
- Model: `gemma3:4b`

To use a different compatible local model, set `OLLAMA_MODEL`.

macOS / Linux:

```bash
export OLLAMA_MODEL="gemma3:4b"
export OLLAMA_HOST="http://localhost:11434"
```

Windows PowerShell:

```powershell
$env:OLLAMA_MODEL="gemma3:4b"
$env:OLLAMA_HOST="http://localhost:11434"
```

These variables are optional when using the defaults. The selected model must already be available in Ollama.

## 4. Run unit tests

From the project directory, with the virtual environment activated:

```bash
python -m unittest discover -s tests -v
```

The tests validate input handling, response validation, and safety guards. They do not call Ollama.

## 5. Run the example migration

```bash
python api_agent.py
```

The program reads:

- `examples/sample_changelog.txt`
- `examples/old_client.py`

It sends the inputs to the local Ollama model and prints a JSON report.

The sample payment API is fictional. The generated migration is a proposal and may be incorrect; review and test it before use.

## 6. Test unaffected code

A separate manual test checks whether unrelated code is left unchanged:

```bash
python -m examples.unaffected_demo
```

For the current greeting-function example, the expected result is:

- `breaking_change`: `True` (the changelog describes a removal)
- `affected`: `False`
- `affected_usages`: an empty list
- `updated_code` exactly matches the original source

## 7. Call the agent from another Python file

```python
from pathlib import Path
from api_agent import generate_migration

root = Path(__file__).resolve().parent

changelog = (root / "examples" / "sample_changelog.txt").read_text(
    encoding="utf-8"
)
source_code = (root / "examples" / "old_client.py").read_text(
    encoding="utf-8"
)

result = generate_migration(changelog, source_code)

print("Affected:", result["affected"])
print("Explanation:", result["explanation"])
print("Proposed code:\n", result["updated_code"])
```

## 8. Shared output contract

The function `generate_migration(changelog, source_code)` returns a dictionary with these fields:

| Field | Type | Meaning |
|---|---|---|
| `breaking_change` | Boolean | Whether the changelog describes a breaking change |
| `affected` | Boolean | Whether the source code is classified as affected |
| `affected_usages` | List of strings | Code usages identified as affected |
| `updated_code` | String | Proposed migrated code; original code is preserved when classified as unaffected |
| `explanation` | String | Explanation of the result |
| `confidence` | Number from 0 to 1 | Model-reported confidence, not a calibrated probability |
| `assumptions` | List of strings | Assumptions made during the analysis |

Member 2 can import `generate_migration` into the backend. Member 3 can evaluate these fields against a versioned test dataset.

## 9. Limitations and safety

- The model can miss breaking changes or propose an incorrect migration.
- The Python usage check is a lightweight safeguard, not a complete static analyzer. It can miss indirect dependencies and may need improvement for other languages.
- Model-reported confidence is not proof of correctness.
- The agent proposes code but does not prove that the patch compiles or passes tests.
- Never execute generated code directly on your laptop or in production without review. Use an isolated sandbox, resource limits, and appropriate tests.
- Do not submit secrets, tokens, or private code to external services without authorization. This version uses a local Ollama endpoint by default.
- A stronger implementation could compare API specifications, parse source ASTs, apply explicit migration rules, and validate patches with automated tests.
