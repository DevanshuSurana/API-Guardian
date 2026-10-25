
# ============================================================
# API Guardian - Code Validation Service
# File: backend/services/code_validation_service.py
#
# Purpose:
#   Detect potentially unresolved Python names in AI code.
# ============================================================

import ast
import builtins
import json
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path


def find_unresolved_names(source_code: str) -> list[str]:
    """
    Find names used but not defined or imported.

    This is a lightweight static check, not a complete
    Python scope analyzer.
    """

    tree = ast.parse(source_code)

    defined_names = set(dir(builtins))
    used_names = set()

    for node in ast.walk(tree):

        # Function definitions
        if isinstance(
            node,
            (ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            defined_names.add(node.name)

            for argument in (
                node.args.posonlyargs
                + node.args.args
                + node.args.kwonlyargs
            ):
                defined_names.add(argument.arg)

            if node.args.vararg:
                defined_names.add(node.args.vararg.arg)

            if node.args.kwarg:
                defined_names.add(node.args.kwarg.arg)

        # Class definitions
        elif isinstance(node, ast.ClassDef):
            defined_names.add(node.name)

        # Imports
        elif isinstance(node, ast.Import):
            for alias in node.names:
                defined_names.add(
                    alias.asname or alias.name.split(".")[0]
                )

        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                defined_names.add(
                    alias.asname or alias.name
                )

        # Assigned variables
        elif isinstance(node, ast.Name):
            if isinstance(node.ctx, (ast.Store, ast.Param)):
                defined_names.add(node.id)

            elif isinstance(node.ctx, ast.Load):
                used_names.add(node.id)

    return sorted(used_names - defined_names)

class CodeValidationError(Exception):
    """Raised when generated code fails validation."""


def _undefined_name_issues(
    source_code: str,
    file_path: str,
) -> list[dict]:
    """Return Ruff F821 diagnostics after checking Python syntax."""

    try:
        ast.parse(source_code, filename=file_path)
    except SyntaxError as error:
        raise CodeValidationError(
            f"Syntax error at line {error.lineno}: {error.msg}"
        ) from error

    with tempfile.TemporaryDirectory() as directory:
        temporary_file = Path(directory) / "candidate.py"
        temporary_file.write_text(source_code, encoding="utf-8")

        try:
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "ruff",
                    "check",
                    "--isolated",
                    "--select",
                    "F821",
                    "--output-format",
                    "json",
                    str(temporary_file),
                ],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise CodeValidationError(
                f"Unable to run Ruff: {error}"
            ) from error

        if result.returncode not in (0, 1):
            raise CodeValidationError(
                f"Ruff validation failed: {result.stderr}"
            )

        try:
            issues = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise CodeValidationError(
                "Ruff returned an invalid response."
            ) from error

    return issues


def validate_generated_python(
    source_code: str,
    file_path: str,
) -> dict:
    """Validate Python syntax and undefined names without executing code."""
    issues = _undefined_name_issues(source_code, file_path)
    if issues:
        details = [
            {
                "line": issue["location"]["row"],
                "message": issue["message"],
                "rule": issue["code"],
            }
            for issue in issues
        ]

        raise CodeValidationError(
            f"Undefined names detected: {details}"
        )

    return {
        "file_path": file_path,
        "syntax_valid": True,
        "undefined_names": [],
        "status": "passed",
    }


def validate_generated_python_change(
    original_code: str,
    updated_code: str,
    file_path: str,
) -> dict:
    """Reject generated edits that introduce new undefined Python names."""
    original_issues = _undefined_name_issues(original_code, file_path)
    updated_issues = _undefined_name_issues(updated_code, file_path)

    existing = Counter(
        (issue.get("code"), issue.get("message"))
        for issue in original_issues
    )
    introduced = []
    for issue in updated_issues:
        key = (issue.get("code"), issue.get("message"))
        if existing[key]:
            existing[key] -= 1
        else:
            introduced.append(issue)

    if introduced:
        details = [
            {
                "line": issue["location"]["row"],
                "message": issue["message"],
                "rule": issue["code"],
            }
            for issue in introduced
        ]
        raise CodeValidationError(
            f"Proposed change introduces undefined names: {details}"
        )

    return {
        "file_path": file_path,
        "syntax_valid": True,
        "new_undefined_names": [],
        "status": "passed",
    }
