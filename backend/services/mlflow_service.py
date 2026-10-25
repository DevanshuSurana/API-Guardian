"""Optional MLflow tracking for live scans and DVC evaluation runs."""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TRACKING_URI = f"sqlite:///{PROJECT_ROOT / 'mlflow.db'}"
LIVE_EXPERIMENT = "api-guardian-live-analysis"
DVC_EXPERIMENT = "api-guardian-dvc-evaluation"


def _mlflow():
    try:
        import mlflow
    except ImportError:
        return None
    try:
        mlflow.set_tracking_uri(os.getenv("MLFLOW_TRACKING_URI", DEFAULT_TRACKING_URI))
    except Exception:  # noqa: BLE001 - tracking is optional and must not break scans.
        return None
    return mlflow


def log_live_analysis(
    *,
    repository: str,
    breaking_change: bool,
    affected_file_count: int,
    status: str,
    duration_seconds: float,
    model: str,
    file_paths: list[str],
) -> str | None:
    """Log safe run metadata; omit source code and full model output."""
    mlflow = _mlflow()
    if mlflow is None:
        return None
    try:
        mlflow.set_experiment(LIVE_EXPERIMENT)
        with mlflow.start_run(run_name=repository.replace("/", "-")) as run:
            mlflow.log_params(
                {
                    "repository": repository,
                    "model": model,
                    "analysis_status": status,
                }
            )
            mlflow.log_metrics(
                {
                    "breaking_change": int(breaking_change),
                    "affected_file_count": affected_file_count,
                    "duration_seconds": duration_seconds,
                }
            )
            mlflow.log_text(
                json.dumps({"repository": repository, "files": file_paths}, indent=2),
                "analysis_summary.json",
            )
            return run.info.run_id
    except Exception:  # noqa: BLE001 - tracking failures must not fail a scan.
        # Tracking should never turn a successful repository scan into a failure.
        return None


def log_dvc_evaluation(report: dict[str, Any], report_path: Path) -> str | None:
    """Log the DVC fixture-baseline report in a clearly named MLflow run."""
    mlflow = _mlflow()
    if mlflow is None:
        return None
    try:
        mlflow.set_experiment(DVC_EXPERIMENT)
        with mlflow.start_run(run_name="dvc-fixture-baseline") as run:
            mlflow.log_params(
                {
                    "prediction_source": report.get("prediction_source", "unknown"),
                    "dataset": report.get("dataset", "unknown"),
                    "case_count": len(report.get("case_results", [])),
                }
            )
            metrics = {}
            for group, values in (
                ("detection", report.get("detection", {})),
                ("patch", report.get("patches", {})),
            ):
                metrics.update(
                    {
                        f"{group}_{key}": float(value)
                        for key, value in values.items()
                        if isinstance(value, (int, float))
                        and not isinstance(value, bool)
                    }
                )
            if metrics:
                mlflow.log_metrics(metrics)
            mlflow.log_artifact(str(report_path))
            return run.info.run_id
    except Exception:  # noqa: BLE001 - tracking failures must not fail DVC output.
        return None


def latest_runs(limit: int = 8) -> dict[str, Any]:
    """Return recent MLflow runs for display in the local UI."""
    mlflow = _mlflow()
    if mlflow is None:
        return {"available": False, "runs": []}
    try:
        experiments = mlflow.search_experiments()
        experiment_names = {
            experiment.experiment_id: experiment.name for experiment in experiments
        }
        experiment_ids = list(experiment_names)
        if not experiment_ids:
            return {"available": True, "runs": []}
        frame = mlflow.search_runs(
            experiment_ids=experiment_ids,
            order_by=["start_time DESC"],
            max_results=limit,
        )
        runs = []
        for _, row in frame.iterrows():
            metrics = {}
            for key, value in row.items():
                key = str(key)
                if not key.startswith("metrics.") or value is None:
                    continue
                try:
                    number = float(value)
                except (TypeError, ValueError):
                    continue
                # MLflow represents metrics that were never logged as NaN.
                # JSON responses must contain finite numbers only.
                if math.isfinite(number):
                    metrics[key[len("metrics.") :]] = number
            experiment_id = str(row.get("experiment_id", ""))
            runs.append(
                {
                    "run_id": row.get("run_id"),
                    "run_name": row.get("tags.mlflow.runName", "run"),
                    "experiment_name": experiment_names.get(experiment_id, ""),
                    "status": row.get("status", ""),
                    "start_time": str(row.get("start_time", "")),
                    "metrics": metrics,
                }
            )
        return {"available": True, "runs": runs}
    except Exception as error:  # noqa: BLE001 - return a UI-readable tracking error.
        return {"available": False, "runs": [], "detail": str(error)}
