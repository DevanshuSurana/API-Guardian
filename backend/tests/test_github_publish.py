
# ============================================================
# API Guardian - GitHub Publishing Dry-Run Test
# File: backend/test_github_publish.py
#
# Purpose:
#   Verify publishing plans and repository restrictions
#   without making GitHub modifications.
#
# Python: 3.10+
# ============================================================

import json

from models.schemas import MigrationPlanResponse
from services.github_publish_service import (
    build_publish_plan,
)


def test_publish_plan():
    """Verify a valid migration produces a dry-run plan."""

    migration = MigrationPlanResponse(
        repository="sneha0832/api-guardian-test-repo",
        branch_name="api-guardian/migration-abc123",
        changed_files=["api_client.py", "checkout.py"],
        total_changed_files=2,
        diff="Example Git diff",
        commit_plan={
            "commit_message": "fix: migrate deprecated API usage",
            "files": ["api_client.py", "checkout.py"],
        },
        pull_request={
            "title": "fix: migrate deprecated API usage",
            "body": "Update deprecated API calls.",
            "head": "api-guardian/migration-abc123",
            "base": "main",
            "draft": True,
        },
        status="migration_plan_prepared",
    )

    # Generate a publishing plan.
    result = build_publish_plan(migration)

    print("=== GITHUB PUBLISHING DRY RUN ===")
    print(json.dumps(result, indent=2))

    # Verify no publishing is enabled.
    assert result["remote_writes_enabled"] is False
    assert result["status"] == "dry_run_only"
    assert len(result["operations"]) == 3

    print("\nGitHub publishing dry-run test passed!")


def test_restricted_repository():
    """Verify that unapproved repositories are rejected."""

    migration = MigrationPlanResponse(
        repository="DevanshuSurana/API-Guardian",
        branch_name="api-guardian/migration-abc123",
        changed_files=["api_client.py"],
        total_changed_files=1,
        diff="Example Git diff",
        commit_plan={
            "commit_message": "fix: migrate API",
            "files": ["api_client.py"],
        },
        pull_request={
            "title": "fix: migrate API",
            "body": "Update deprecated API calls.",
            "head": "api-guardian/migration-abc123",
            "base": "main",
            "draft": True,
        },
        status="migration_plan_prepared",
    )

    try:
        build_publish_plan(migration)

    except ValueError as error:
        print("\nRestricted repository correctly rejected:")
        print(error)
        return

    raise AssertionError(
        "Unapproved repository should have been rejected."
    )


if __name__ == "__main__":
    test_publish_plan()
    test_restricted_repository()
