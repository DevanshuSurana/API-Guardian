
# ============================================================
# API Guardian - GitHub Publishing Service
# File: backend/services/github_publish_service.py
#
# Purpose:
#   Prepare a safe GitHub publishing plan for migrations.
#
# ============================================================

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

    if repository not in ALLOWED_REPOSITORIES:
        raise ValueError(
            f"Repository is not approved for publishing: {repository}"
        )


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
        "remote_writes_enabled": REMOTE_WRITES_ENABLED,
        "status": "dry_run_only",
    }
