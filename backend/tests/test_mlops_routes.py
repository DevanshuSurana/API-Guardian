import json
import subprocess

import pytest
from fastapi import HTTPException

from routes import mlops


def test_status_reports_dvc_from_the_running_virtual_environment(tmp_path, monkeypatch):
    environment_bin = tmp_path / "bin"
    environment_bin.mkdir()
    executable = environment_bin / "dvc"
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    executable.chmod(executable.stat().st_mode | 0o111)
    monkeypatch.setattr(mlops.shutil, "which", lambda _name: None)
    monkeypatch.setattr(mlops.sys, "executable", str(environment_bin / "python"))
    monkeypatch.setattr(mlops, "_dvc_version", lambda executable: "3.0.0")
    monkeypatch.setattr(
        mlops, "_evaluation_config", lambda: ({"report": "out.json"}, None)
    )

    status = mlops.mlops_status()

    assert status["dvc_available"] is True
    assert status["dvc_version"] == "3.0.0"
    assert status["evaluation_config_available"] is True


def test_status_exposes_missing_evaluation_config_without_failing(monkeypatch):
    monkeypatch.setattr(mlops, "_find_dvc_executable", lambda: None)
    monkeypatch.setattr(
        mlops,
        "_evaluation_config",
        lambda: ({}, "params.yaml must define evaluation.report."),
    )

    status = mlops.mlops_status()

    assert status["dvc_available"] is False
    assert status["evaluation_config_available"] is False
    assert (
        status["evaluation_config_error"]
        == "params.yaml must define evaluation.report."
    )


def test_dvc_repro_returns_report_and_logs_run(tmp_path, monkeypatch):
    report_relative = "reports/latest.json"
    report_path = tmp_path / report_relative
    report_path.parent.mkdir()
    report = {"case_results": [{"id": "case-1"}], "detection": {"accuracy": 1.0}}
    report_path.write_text(json.dumps(report), encoding="utf-8")
    (tmp_path / "params.yaml").write_text(
        f"evaluation:\n  report: {report_relative}\n", encoding="utf-8"
    )
    monkeypatch.setattr(mlops, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(mlops, "_find_dvc_executable", lambda: "/fake/dvc")
    monkeypatch.setattr(
        mlops.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=["dvc", "repro"], returncode=0, stdout="Stage reproduced", stderr=""
        ),
    )
    monkeypatch.setattr(mlops, "log_dvc_evaluation", lambda *_args: "run-123")

    result = mlops.run_dvc_evaluation()

    assert result["report"] == report
    assert result["mlflow_run_id"] == "run-123"
    assert "smoke evaluation" in result["note"]


def test_dvc_repro_reports_missing_install_and_timed_out_run(monkeypatch):
    monkeypatch.setattr(mlops, "_find_dvc_executable", lambda: None)
    with pytest.raises(HTTPException) as missing:
        mlops.run_dvc_evaluation()
    assert missing.value.status_code == 503

    monkeypatch.setattr(mlops, "_find_dvc_executable", lambda: "/fake/dvc")
    monkeypatch.setattr(
        mlops, "_evaluation_config", lambda: ({"report": "report.json"}, None)
    )

    def timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired("dvc repro", 600)

    monkeypatch.setattr(mlops.subprocess, "run", timeout)
    with pytest.raises(HTTPException) as timed_out:
        mlops.run_dvc_evaluation()
    assert timed_out.value.status_code == 504
