
# ============================================================
# API Guardian - GitHub Publishing Service
# File: backend/services/github_publish_service.py
#
# Purpose:
#   Prepare a safe GitHub publishing plan for migrations.
#
# ============================================================

import os
from typing import Any

from models.schemas import MigrationPlanResponse

# Only this repository may be used for publishing tests.
ALLOWED_REPOSITORIES = {
    "sneha0832/api-guardian-test-repo",
}

# Safety switch: remote publishing is disabled.
REMOTE_WRITES_ENABLED = False


def validate_publish_target(repository: str) -> None:
    """
    Ensure the target repository is explicitly allowed.
    """

    if not is_publish_target_allowed(repository):
        raise ValueError(
            f"Repository is not approved for publishing: {repository}"
        )


def allowed_repositories() -> set[str]:
    """Return the explicitly configured destinations for remote writes."""
    configured = os.getenv("API_GUARDIAN_ALLOWED_REPOSITORIES")
    if configured is None:
        return {repository.lower() for repository in ALLOWED_REPOSITORIES}
    return {
        repository.strip().lower()
        for repository in configured.split(",")
        if repository.strip()
    }


def is_publish_target_allowed(repository: str | None) -> bool:
    """Check whether a canonical owner/repository target is allowlisted."""
    return bool(repository) and repository.strip().lower() in allowed_repositories()


def publishing_readiness(repository: str | None = None) -> dict[str, Any]:
    """Describe publishing setup while never returning secret values."""
    writes_enabled = os.getenv("API_GUARDIAN_ENABLE_PUBLISH") == "true"
    token_configured = bool(os.getenv("GITHUB_TOKEN", "").strip())
    repository_approved = (
        is_publish_target_allowed(repository) if repository else False
    )
    issues = []
    if repository and not repository_approved:
        issues.append(
            "Add this exact owner/repository to API_GUARDIAN_ALLOWED_REPOSITORIES in backend/.env."
        )
    if not token_configured:
        issues.append("Set GITHUB_TOKEN in backend/.env with repository write and pull request permissions.")
    if not writes_enabled:
        issues.append("Set API_GUARDIAN_ENABLE_PUBLISH=true in backend/.env to enable publishing.")
    return {
        "repository": repository,
        "repository_approved": repository_approved,
        "token_configured": token_configured,
        "remote_writes_enabled": writes_enabled,
        "publish_ready": bool(repository and repository_approved and token_configured and writes_enabled),
        "readiness_issues": issues,
    }


def build_publish_plan(
    migration: MigrationPlanResponse,
) -> dict[str, Any]:
    """
    Prepare the GitHub publishing operations.

    This function only describes what would happen.
    It never executes Git commands or GitHub API writes.
    """

    # Step 1: Verify the destination repository.
    validate_publish_target(migration.repository)

    # Step 2: Verify that the migration has modified files.
    if not migration.changed_files:
        raise ValueError(
            "Cannot publish a migration without changed files."
        )

    # Step 3: Validate the prepared branch.
    branch_name = migration.branch_name

    if not branch_name.startswith("api-guardian/migration-"):
        raise ValueError(
            "Invalid migration branch."
        )

    # Step 4: Retrieve the prepared commit message.
    commit_message = migration.commit_plan.get(
        "commit_message"
    )

    if not commit_message:
        raise ValueError(
            "Missing commit message."
        )

    # Step 5: Retrieve the prepared PR payload.
    pr_payload = migration.pull_request

    if pr_payload.get("head") != branch_name:
        raise ValueError(
            "Pull request head does not match migration branch."
        )

    if not pr_payload.get("draft", False):
        raise ValueError(
            "Only draft pull requests are permitted."
        )

    # Step 6: Describe the future publishing operations.
    operations = [
        {
            "step": 1,
            "action": "create_local_commit",
            "branch": branch_name,
            "files": migration.changed_files,
            "message": commit_message,
        },
        {
            "step": 2,
            "action": "push_migration_branch",
            "branch": branch_name,
        },
        {
            "step": 3,
            "action": "create_draft_pull_request",
            "payload": pr_payload,
        },
    ]

    # Step 7: Return the plan without executing anything.
    return {
        "repository": migration.repository,
        "branch_name": branch_name,
        "operations": operations,
        "remote_writes_enabled": os.getenv("API_GUARDIAN_ENABLE_PUBLISH") == "true",
        "status": "dry_run_only",
    }
