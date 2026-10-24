"""Small reusable MLflow logging helper."""
from __future__ import annotations

def log_evaluation(experiment_name: str, run_name: str, params: dict, metrics: dict, artifact_path: str | None = None) -> None:
    try:
        import mlflow
    except ImportError as exc:
        raise RuntimeError("Install dependencies with: pip install -r requirements-mlops.txt") from exc
    mlflow.set_experiment(experiment_name)
    with mlflow.start_run(run_name=run_name):
        if params:
            mlflow.log_params({k: str(v) for k, v in params.items()})
        if metrics:
            mlflow.log_metrics({k: float(v) for k, v in metrics.items()})
        if artifact_path:
            mlflow.log_artifact(artifact_path)
