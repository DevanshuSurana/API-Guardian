from services.scan_history_service import record_scan_findings


def _finding(branch="main"):
    return {
        "file_path": "app/client.py",
        "branch": branch,
        "severity": "high",
        "title": "Removed API argument",
        "evidence": "client.request(old_arg=True)",
        "explanation": "The API removed this argument.",
        "recommendation": "Use the new argument.",
        "proposed_code": None,
        "verification_status": "no_fix",
    }


def test_scan_history_deduplicates_and_resolves_only_scanned_branch(tmp_path):
    database = tmp_path / "scan-history.db"
    revisions = [
        {"branch": "main", "commit_sha": "a" * 40},
        {"branch": "release", "commit_sha": "b" * 40},
    ]
    current, resolved = record_scan_findings(
        "owner/repo",
        "scan-1",
        revisions,
        [_finding(), _finding(), _finding("release")],
        reconcile=True,
        database_path=database,
    )

    assert len(current) == 2
    assert all(item["lifecycle_status"] == "new" for item in current)
    assert all(item["fingerprint"] for item in current)
    assert resolved == []

    current, resolved = record_scan_findings(
        "owner/repo",
        "scan-2",
        [{"branch": "main", "commit_sha": "c" * 40}],
        [],
        reconcile=True,
        database_path=database,
    )

    assert current == []
    assert len(resolved) == 1
    assert resolved[0]["lifecycle_status"] == "resolved"
    assert resolved[0]["resolved_in_commit_sha"] == "c" * 40
    assert resolved[0]["proposed_code"] is None
    assert resolved[0]["evidence"] == ""

    current, resolved = record_scan_findings(
        "owner/repo",
        "scan-3",
        [{"branch": "release", "commit_sha": "d" * 40}],
        [_finding("release")],
        reconcile=True,
        database_path=database,
    )

    assert len(current) == 1
    assert current[0]["lifecycle_status"] == "open"
    assert resolved == []


def test_targeted_scan_does_not_resolve_prior_findings(tmp_path):
    database = tmp_path / "scan-history.db"
    revisions = [{"branch": "main", "commit_sha": "a" * 40}]
    record_scan_findings(
        "owner/repo",
        "scan-1",
        revisions,
        [_finding()],
        reconcile=True,
        database_path=database,
    )

    _, resolved = record_scan_findings(
        "owner/repo",
        "targeted-scan",
        [{"branch": "main", "commit_sha": "b" * 40}],
        [],
        reconcile=False,
        database_path=database,
    )
    assert resolved == []

    _, resolved = record_scan_findings(
        "owner/repo",
        "full-scan",
        [{"branch": "main", "commit_sha": "c" * 40}],
        [],
        reconcile=True,
        database_path=database,
    )
    assert len(resolved) == 1
