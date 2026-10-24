# API Guardian — Member 3: MLOps and Evaluation

Member 3 owns the evaluation data, repeatable evaluation pipeline, and experiment reporting for API Guardian. This work helps the team measure whether the agent detects breaking API changes and whether its proposed migrations pass tests.

## Current contents

- `datasets/api_changes/api_changes.jsonl`: 12 labeled breaking and non-breaking API change cases, including fixture-only baseline predictions.
- `datasets/migration_cases/migration_cases.jsonl`: 12 matching migration examples with expected affected files and behavior.
- `mlops/metrics.py`: detection and patch outcome metrics.
- `mlops/evaluation/evaluate.py`: evaluation CLI that writes a JSON report and can optionally log metrics to MLflow.
- `dvc.yaml` and `dvc.lock`: a DVC evaluation stage that records the input and output hashes.
- `tests/test_metrics.py`: unit tests for the metric calculations.

The migration examples are synthetic fixtures. Their affected file paths describe example projects; they do not refer to files in the API Guardian repository.

> **Baseline warning:** `baseline_prediction` and the other `baseline_*` fields are fixture values for checking that the evaluation pipeline runs. They are not measurements of the real API Guardian agent. Do not report them as agent performance.

## Setup in VS Code

Open the repository root in VS Code and activate the project virtual environment in the integrated terminal. If `.venv` does not exist yet, create it first with one of the commands below; skip the creation command when reusing an existing environment.

macOS/Linux:

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-mlops.txt
python -m pip install -e .
```

Windows PowerShell:

```powershell
py -3.13 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements-mlops.txt
python -m pip install -e .
```

The project supports Python `>=3.13,<3.15`.

## Run and validate

Run the unit tests:

```bash
python -m pytest -q
```

Run the bundled fixture evaluation without MLflow:

```bash
python -m mlops.evaluation.evaluate --no-mlflow --output mlops/evaluation/reports/local-report.json
```

Run the same evaluation through DVC and check reproducibility:

```bash
dvc repro
dvc status
```

`dvc repro` writes `mlops/evaluation/reports/latest.json` (ignored by Git) and updates `dvc.lock` when inputs or outputs change. The current DVC setup tracks stage dependencies and hashes in the lockfile; no DVC remote is configured for sharing dataset objects.

The report includes detection precision, recall, F1, accuracy, confusion counts, patch generation/pass rates, regressions, and a per-case detection result. The current fixture run covers 12 cases. It does not measure latency or cost.

## Evaluate real agent predictions

Create a JSONL prediction file with one record per `case_id` in `api_changes.jsonl`:

```json
{"case_id":"rename_method_001","detected_breaking":true,"patch_generated":true,"tests_passed":true,"regression_detected":false}
```

Run the evaluator against that file:

```bash
python -m mlops.evaluation.evaluate \
  --predictions path/to/predictions.jsonl \
  --run-name agent-v1 \
  --output mlops/evaluation/reports/agent-v1-report.json
```

Prediction rows must use the dataset's exact case IDs and include `detected_breaking`. Patch fields are `patch_generated`, `tests_passed`, and `regression_detected`.

Keep ground truth and predictions separate. Do not include `expected_breaking` or `expected_migration` in the agent prompt; doing so leaks the answer.

## MLflow tracking

The evaluator logs a run to the local MLflow tracking store by default when MLflow is installed:

```bash
python -m mlops.evaluation.evaluate --run-name agent-v1
mlflow ui --host 127.0.0.1 --port 5000
```

Open <http://127.0.0.1:5000> to inspect runs. Use a distinct `--run-name` for each prompt or model configuration being compared.

## Current limits and next integration steps

- The backend is now wired to the local Ollama agent, but the evaluator still only has fixture predictions. Generate prediction JSONL from real agent runs before reporting agent performance.
- Compare at least two prompt or model configurations using the same cases.
- Extend the result schema and evaluator to capture latency and cost.
- Confirm patch success against real test execution, rather than relying only on prediction fields.
- Configure a DVC remote if the team needs to share dataset objects outside Git.

## Member 2 integration contract

Recommended input to the agent: one API change plus relevant source code, without ground-truth fields.

Recommended output: one prediction row per case in the format above. The evaluation CLI joins predictions to labels by `case_id` and reports detection and patch outcomes.
