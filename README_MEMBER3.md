# API Guardian — Member 3 MLOps starter

## What this includes
- JSONL evaluation dataset with labeled breaking/non-breaking examples.
- Detection metrics: precision, recall, F1, accuracy, confusion counts.
- Patch metrics: patch generation, test-pass rate, and regression rate.
- JSON evaluation reports.
- Optional MLflow experiment tracking.
- DVC evaluation pipeline.
- Unit tests.

> Important: the built-in baseline is only a pipeline smoke test. It does not measure the real API Guardian agent. Replace the baseline prediction adapter or provide real prediction JSONL from Member 2 before reporting agent performance.

## Setup (from repository root)
```bash
python -m venv .venv
# macOS/Linux
source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements-mlops.txt
pip install -e .
```

If you do not want MLflow/DVC yet, the evaluator itself uses only Python's standard library:
```bash
python -m mlops.evaluation.evaluate --no-mlflow
```

Run tests:
```bash
python -m pytest
```

## DVC
Initialize DVC once at repository root if not already initialized:
```bash
dvc init
```
Do not run `dvc init` again if the repository already has `.dvc/`.
Run pipeline:
```bash
dvc repro
```

## MLflow
Run evaluation with MLflow enabled:
```bash
python -m mlops.evaluation.evaluate
mlflow ui --host 127.0.0.1 --port 5000
```
Open http://127.0.0.1:5000 locally.

## Real-agent prediction format
Create a JSONL file with one row per dataset case. The `case_id` must match exactly:
```json
{"case_id":"rename_method_001","detected_breaking":true,"patch_generated":true,"tests_passed":true,"regression_detected":false}
```
Then run:
```bash
python -m mlops.evaluation.evaluate --predictions path/to/predictions.jsonl --run-name prompt-v2
```

## Dataset fields
- `case_id`: unique stable ID.
- `category`: breaking-change category.
- `old_api`, `new_api`: concise API signatures or descriptions.
- `expected_breaking`: ground-truth label.
- `expected_migration`: intended migration guidance.
- `baseline_prediction`: fixture-only prediction used for smoke testing.
- `baseline_patch_generated`, `baseline_tests_passed`, `baseline_regression_detected`: fixture-only patch fields.

## Integration contract with Member 2
Recommended adapter input: one case containing old/new API details and source code.
Recommended adapter output:
```json
{
  "case_id": "rename_method_001",
  "detected_breaking": true,
  "patch_generated": true,
  "tests_passed": true,
  "regression_detected": false
}
```
Keep ground truth separate from agent output. Never pass `expected_breaking` or `expected_migration` to the model prompt; that would leak the answer.
