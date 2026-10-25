"""Local MLflow and DVC endpoints used by the dashboard."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, HTTPException
from services.mlflow_service import latest_runs, log_dvc_evaluation

router = APIRouter(prefix="/api/mlops", tags=["MLOps"])
PROJECT_ROOT = Path(__file__).resolve().parents[2]


@router.get("/status")
def mlops_status() -> dict[str, Any]:
    """Report whether MLflow, DVC, and the local evaluation config are ready."""
    try:
        import mlflow
    except ImportError:
        mlflow_available = False
        mlflow_version = None
    else:
        mlflow_available = True
        mlflow_version = mlflow.__version__

    dvc_executable = _find_dvc_executable()
    evaluation, config_error = _evaluation_config()
    return {
        "ollama_model": os.getenv("OLLAMA_MODEL", "gemma3:4b"),
        "mlflow_available": mlflow_available,
        "mlflow_version": mlflow_version,
        "dvc_available": dvc_executable is not None,
        "dvc_version": _dvc_version(dvc_executable) if dvc_executable else None,
        "dataset": evaluation.get("dataset"),
        "report": evaluation.get("report"),
        "evaluation_config_available": config_error is None,
        "evaluation_config_error": config_error,
    }


@router.get("/runs")
def mlops_runs() -> dict[str, Any]:
    """List recent MLflow runs for the interactive dashboard."""
    return latest_runs()


@router.post("/dvc/repro")
def run_dvc_evaluation() -> dict[str, Any]:
    """Reproduce the fixture-baseline evaluation declared in ``dvc.yaml``."""
    dvc_executable = _find_dvc_executable()
    if dvc_executable is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "DVC is not installed in this Python environment. Install the "
                "project's MLOps requirements and restart the backend."
            ),
        )

    config, config_error = _evaluation_config()
    if config_error:
        raise HTTPException(status_code=500, detail=config_error)

    try:
        completed = subprocess.run(
            [dvc_executable, "repro"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise HTTPException(
            status_code=504, detail="DVC evaluation timed out."
        ) from error
    except OSError as error:
        raise HTTPException(
            status_code=503,
            detail=f"Could not start DVC: {error}",
        ) from error

    if completed.returncode:
        detail = (completed.stderr or completed.stdout or "No DVC output.")[-4000:]
        raise HTTPException(status_code=500, detail=f"DVC repro failed: {detail}")

    report_path = PROJECT_ROOT / config["report"]
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise HTTPException(
            status_code=500,
            detail="DVC completed without creating the configured evaluation report.",
        ) from error
    except (OSError, json.JSONDecodeError) as error:
        raise HTTPException(
            status_code=500,
            detail=f"Could not read the DVC evaluation report: {error}",
        ) from error

    run_id = log_dvc_evaluation(report, report_path)
    return {
        "report": report,
        "mlflow_run_id": run_id,
        "dvc_output": completed.stdout[-3000:],
        "note": "Fixture-baseline smoke evaluation; these are not live-agent metrics.",
    }


def _find_dvc_executable() -> str | None:
    """Find DVC on PATH or next to the Python interpreter running the API."""
    executable = shutil.which("dvc")
    if executable:
        return executable
    interpreter_dvc = Path(sys.executable).parent / "dvc"
    if interpreter_dvc.is_file() and os.access(interpreter_dvc, os.X_OK):
        return str(interpreter_dvc)
    return None


def _evaluation_config() -> tuple[dict[str, Any], str | None]:
    """Load and validate only the DVC fields this API needs."""
    config_path = PROJECT_ROOT / "params.yaml"
    try:
        payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}, f"DVC evaluation config not found: {config_path.name}."
    except (OSError, yaml.YAMLError) as error:
        return {}, f"Could not read {config_path.name}: {error}"

    evaluation = payload.get("evaluation") if isinstance(payload, dict) else None
    if not isinstance(evaluation, dict):
        return {}, f"{config_path.name} must contain an evaluation mapping."
    if (
        not isinstance(evaluation.get("report"), str)
        or not evaluation["report"].strip()
    ):
        return {}, f"{config_path.name} must define evaluation.report."
    return evaluation, None


def _dvc_version(executable: str) -> str | None:
    """Return DVC's version without making readiness checks fail on errors."""
    try:
        result = subprocess.run(
            [executable, "--version"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode:
        return None
    return result.stdout.strip().splitlines()[0] if result.stdout.strip() else None
