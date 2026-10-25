"""Persist branch-scoped scan findings and resolve them after clean audits."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATABASE_PATH = PROJECT_ROOT / "scan-history.db"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()  # noqa: UP017 - Keep Python 3.10 support.


def finding_fingerprint(repository: str, branch: str, file_path: str, title: str) -> str:
    """Build a stable finding identity that survives scans at newer commits."""
    normalized_title = re.sub(r"[^a-z0-9]+", " ", title.casefold()).strip()
    identity = json.dumps(
        [repository.casefold(), branch, file_path, normalized_title],
        separators=(",", ":"),
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]


def _finding_dict(finding: Any) -> dict[str, Any]:
    if isinstance(finding, dict):
        return dict(finding)
    return finding.model_dump(mode="json")


def _history_payload(finding: dict[str, Any]) -> dict[str, Any]:
    """Persist finding metadata without source snippets or proposed source code."""
    fields = (
        "file_path",
        "branch",
        "severity",
        "title",
        "explanation",
        "recommendation",
        "fingerprint",
        "verification_status",
        "verification_message",
        "lifecycle_status",
        "first_seen_at",
        "last_seen_at",
        "resolved_in_commit_sha",
        "resolved_at",
    )
    payload = {field: finding.get(field) for field in fields}
    payload["evidence"] = ""
    payload["proposed_code"] = None
    return payload


def _connect(database_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(database_path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 10000")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS scan_findings (
            repository TEXT NOT NULL,
            branch TEXT NOT NULL,
            fingerprint TEXT NOT NULL,
            lifecycle_status TEXT NOT NULL,
            commit_sha TEXT NOT NULL,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            last_scan_id TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            PRIMARY KEY (repository, branch, fingerprint)
        )
        """
    )
    return connection


def record_scan_findings(
    repository: str,
    scan_id: str,
    revisions: list[dict[str, str]],
    findings: list[Any],
    *,
    reconcile: bool,
    database_path: Path | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Store current findings and resolve missing ones on successfully scanned branches.

    Resolution only runs for complete, untargeted audits. Findings on branches
    that were not scanned remain open. A targeted changelog scan updates what it
    sees without claiming that absent issues have been fixed.
    """
    db_path = database_path or DEFAULT_DATABASE_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    revision_by_branch = {item["branch"]: item["commit_sha"] for item in revisions}

    deduplicated: dict[str, dict[str, Any]] = {}
    for finding in findings:
        item = _finding_dict(finding)
        branch = str(item["branch"])
        fingerprint = finding_fingerprint(
            repository,
            branch,
            str(item["file_path"]),
            str(item["title"]),
        )
        item["fingerprint"] = fingerprint
        deduplicated.setdefault(fingerprint, item)

    deduplicated_by_branch: dict[str, dict[str, dict[str, Any]]] = {}
    for fingerprint, item in deduplicated.items():
        deduplicated_by_branch.setdefault(item["branch"], {})[fingerprint] = item

    current_results: list[dict[str, Any]] = []
    resolved_results: list[dict[str, Any]] = []
    now = _now()
    connection = _connect(db_path)
    try:
        with connection:
            for branch, commit_sha in revision_by_branch.items():
                current = deduplicated_by_branch.get(branch, {})
                previous_rows = connection.execute(
                    """
                    SELECT fingerprint, lifecycle_status, first_seen_at, payload_json
                    FROM scan_findings
                    WHERE repository = ? AND branch = ?
                    """,
                    (repository, branch),
                ).fetchall()
                previous_by_id = {row["fingerprint"]: row for row in previous_rows}

                for fingerprint, item in current.items():
                    previous = previous_by_id.get(fingerprint)
                    first_seen = (
                        previous["first_seen_at"]
                        if previous and previous["lifecycle_status"] == "open"
                        else now
                    )
                    lifecycle = (
                        "open"
                        if previous and previous["lifecycle_status"] == "open"
                        else "new"
                    )
                    item["lifecycle_status"] = lifecycle
                    item["first_seen_at"] = first_seen
                    item["last_seen_at"] = now
                    item["resolved_in_commit_sha"] = None
                    connection.execute(
                        """
                        INSERT INTO scan_findings (
                            repository, branch, fingerprint, lifecycle_status,
                            commit_sha, first_seen_at, last_seen_at, last_scan_id,
                            payload_json
                        ) VALUES (?, ?, ?, 'open', ?, ?, ?, ?, ?)
                        ON CONFLICT(repository, branch, fingerprint) DO UPDATE SET
                            lifecycle_status = 'open',
                            commit_sha = excluded.commit_sha,
                            last_seen_at = excluded.last_seen_at,
                            last_scan_id = excluded.last_scan_id,
                            payload_json = excluded.payload_json
                        """,
                        (
                            repository,
                            branch,
                            fingerprint,
                            commit_sha,
                            first_seen,
                            now,
                            scan_id,
                            json.dumps(_history_payload(item), sort_keys=True),
                        ),
                    )
                    current_results.append(item)

                if not reconcile:
                    continue

                for fingerprint, previous in previous_by_id.items():
                    if previous["lifecycle_status"] != "open" or fingerprint in current:
                        continue
                    old_item = json.loads(previous["payload_json"])
                    old_item["lifecycle_status"] = "resolved"
                    old_item["resolved_in_commit_sha"] = commit_sha
                    old_item["resolved_at"] = now
                    connection.execute(
                        """
                        UPDATE scan_findings
                        SET lifecycle_status = 'resolved',
                            commit_sha = ?, last_scan_id = ?, payload_json = ?
                        WHERE repository = ? AND branch = ? AND fingerprint = ?
                        """,
                        (
                            commit_sha,
                            scan_id,
                            json.dumps(old_item, sort_keys=True),
                            repository,
                            branch,
                            fingerprint,
                        ),
                    )
                    resolved_results.append(old_item)
    finally:
        connection.close()

    return current_results, resolved_results
