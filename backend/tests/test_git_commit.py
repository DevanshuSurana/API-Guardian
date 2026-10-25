
# ============================================================
# API Guardian - Git Commit Preparation Test
# File: backend/test_git_commit.py
#
# Purpose:
#   Test Git commit planning using a temporary clone
#   of the API Guardian test repository.
#
#   No commits or remote writes are performed.
# ============================================================

import pytest

from models.schemas import FileChange
from services.batch_patch_service import (
    apply_batch,
)
from services.git_branch_service import (
    create_migration_branch,
)
from services.git_commit_service import (
    prepare_git_commit,
)
from services.repository_service import (
    cleanup_workspace,
    clone_repository,
)


@pytest.mark.integration
def test_git_commit_preparation():
    """Verify commit preparation without creating a commit."""

    workspace = None

    try:
        # Step 1: Clone the public test repository.
        workspace, repository_path = clone_repository(
            "sneha0832",
            "api-guardian-test-repo",
        )

        # Step 2: Create a local migration branch.
        branch_name = create_migration_branch(
            str(repository_path)
        )

        # Step 3: Define proposed API changes.
        changes = [
            FileChange(
                file_path="api_client.py",
                original_code="client.old_charge(100)",
                updated_code="client.new_charge(100)",
                explanation="Replace deprecated payment API call.",
            ),
            FileChange(
                file_path="checkout.py",
                original_code="client.old_charge(amount)",
                updated_code="client.new_charge(amount)",
                explanation="Update checkout payment API call.",
            ),
        ]

        # Step 4: Apply changes to the temporary clone.
        apply_batch(
            str(repository_path),
            changes,
        )

        # Step 5: Prepare a commit plan.
        result = prepare_git_commit(
            repository_path=str(repository_path),
            changed_files=[
                "api_client.py",
                "checkout.py",
            ],
            commit_message=(
                "fix: replace deprecated payment API calls"
            ),
        )

        print("=== GIT COMMIT PLAN ===")
        print("Branch:", result["branch_name"])
        print("Message:", result["commit_message"])
        print("Files:", result["files"])
        print("Status:", result["status"])

        print("\n=== PROPOSED DIFF ===")
        print(result["diff"])

        # Step 6: Verify the expected results.
        assert result["branch_name"] == branch_name
        assert result["total_files"] == 2
        assert result["status"] == "commit_plan_prepared"
        assert "api_client.py" in result["files"]
        assert "checkout.py" in result["files"]

        print("\nGit commit preparation test passed!")

    finally:
        # Always delete the temporary clone.
        if workspace is not None:
            cleanup_workspace(workspace)


if __name__ == "__main__":
    test_git_commit_preparation()
