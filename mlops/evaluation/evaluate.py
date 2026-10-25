"""Run a deterministic baseline evaluation or evaluate a JSONL prediction file.

Baseline mode is only a smoke test for the evaluation pipeline; it is NOT a
measurement of the real API Guardian agent.
"""
from __future__ import annotations
import argparse, json, os
from pathlib import Path
from mlops.metrics import detection_metrics, patch_metrics

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "datasets" / "api_changes" / "api_changes.jsonl"

def read_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise ValueError(f"Invalid JSON at {path}:{line_no}: {exc}") from exc
    return rows

def baseline_prediction(case: dict) -> dict:
    # A transparent baseline: use the supplied fixture prediction. Replace this
    # function with an adapter calling the Member 2 backend agent.
    return {
        "detected_breaking": bool(case["baseline_prediction"]),
        "patch_generated": bool(case.get("baseline_patch_generated", False)),
        "tests_passed": bool(case.get("baseline_tests_passed", False)),
        "regression_detected": bool(case.get("baseline_regression_detected", False)),
    }

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DATASET)
    parser.add_argument("--output", type=Path, default=ROOT / "mlops" / "evaluation" / "reports" / "latest.json")
    parser.add_argument("--predictions", type=Path, help="Optional JSONL predictions keyed by case_id")
    parser.add_argument("--experiment-name", default="api-guardian-evaluation")
    parser.add_argument("--run-name", default="baseline-smoke-test")
    parser.add_argument("--no-mlflow", action="store_true")
    args = parser.parse_args()

    cases = read_jsonl(args.dataset)
    if not cases:
        raise SystemExit("Dataset is empty.")

    if args.predictions:
        pred_rows = read_jsonl(args.predictions)
        by_id = {r["case_id"]: r for r in pred_rows}
        missing = [c["case_id"] for c in cases if c["case_id"] not in by_id]
        if missing:
            raise SystemExit(f"Missing predictions for cases: {', '.join(missing)}")
        predictions = [by_id[c["case_id"]] for c in cases]
        source = "external_predictions"
    else:
        predictions = [baseline_prediction(c) for c in cases]
        source = "fixture_baseline_not_real_agent"

    detection = detection_metrics(
        [bool(c["expected_breaking"]) for c in cases],
        [bool(p["detected_breaking"]) for p in predictions],
    )
    patch_rows = []
    for p in predictions:
        patch_rows.append({
            "patch_generated": p.get("patch_generated", False),
            "tests_passed": p.get("tests_passed", False),
            "regression_detected": p.get("regression_detected", False),
        })
    patches = patch_metrics(patch_rows)
    report = {
        "experiment_name": args.experiment_name,
        "run_name": args.run_name,
        "prediction_source": source,
        "dataset": str(args.dataset.relative_to(ROOT)) if args.dataset.is_relative_to(ROOT) else str(args.dataset),
        "detection": detection,
        "patches": patches,
        "case_results": [
            {"case_id": c["case_id"], "expected_breaking": c["expected_breaking"],
             "detected_breaking": p["detected_breaking"],
             "correct": bool(c["expected_breaking"]) == bool(p["detected_breaking"])}
            for c, p in zip(cases, predictions)
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")

    if not args.no_mlflow:
        try:
            import mlflow
            mlflow.set_experiment(args.experiment_name)
            with mlflow.start_run(run_name=args.run_name):
                mlflow.log_param("dataset_path", str(args.dataset))
                mlflow.log_param("prediction_source", source)
                mlflow.log_param("case_count", len(cases))
                for key, value in detection.items():
                    if isinstance(value, (int, float)):
                        mlflow.log_metric(f"detection_{key}", value)
                for key, value in patches.items():
                    if isinstance(value, (int, float)):
                        mlflow.log_metric(f"patch_{key}", value)
                mlflow.log_artifact(str(args.output))
        except ImportError:
            print("MLflow not installed; report saved without experiment tracking.")
    print(json.dumps({"report": str(args.output), "source": source,
                      "detection": detection, "patches": patches}, indent=2))

if __name__ == "__main__":
    main()
