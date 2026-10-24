
# ============================================================
# API Guardian - Local Git Commit Test
# File: backend/test_local_commit.py
#
# Purpose:
#   Test the complete local migration commit workflow
#   using the API Guardian test repository.
# ============================================================

import pytest

from git import Repo

from models.schemas import FileChange

from services.repository_service import (
    clone_repository,
    cleanup_workspace,
)

from services.git_branch_service import (
    create_migration_branch,
    get_changed_files,
)

from services.batch_patch_service import apply_batch

from services.git_commit_service import (
    create_local_migration_commit,
)


@pytest.mark.integration
def test_local_commit():
    """
    Clone the test repository, apply API migrations,
    create a local commit, and verify the result.
    """

    workspace = None

    try:
        # Step 1: Clone the test repository.
        workspace, repository_path = clone_repository(
            "sneha0832",
            "api-guardian-test-repo",
        )

        # Step 2: Create a local migration branch.
        branch_name = create_migration_branch(
            str(repository_path)
        )

        # Step 3: Define the API migrations.
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
                explanation="Update checkout payment method.",
            ),
        ]

        # Step 4: Apply the changes to the temporary clone.
        apply_batch(
            str(repository_path),
            changes,
        )

        # Step 5: Identify the modified files.
        changed_files = get_changed_files(
            str(repository_path)
        )

        # Step 6: Create a real Git commit locally.
        result = create_local_migration_commit(
            repository_path=str(repository_path),
            changed_files=changed_files,
            commit_message="fix: replace deprecated payment API calls",
        )

        # Step 7: Verify the result.
        assert result["status"] == "committed_locally"
        assert result["branch_name"] == branch_name
        assert result["total_committed_files"] == 2

        assert sorted(result["committed_files"]) == [
            "api_client.py",
            "checkout.py",
        ]

        # Step 8: Verify Git recognizes the new commit.
        repository = Repo(str(repository_path))

        assert repository.head.commit.hexsha == result["commit_hash"]

        # Step 9: Verify the temporary working tree is clean.
        assert not repository.is_dirty(
            untracked_files=True
        )

        print("=== LOCAL MIGRATION COMMIT ===")
        print("Branch:", result["branch_name"])
        print("Commit:", result["commit_hash"])
        print("Message:", result["commit_message"])
        print("Files:", result["committed_files"])
        print("Status:", result["status"])

        print("\nLocal Git commit test passed!")

    finally:
        # Step 10: Always delete the temporary clone.
        if workspace is not None:
            cleanup_workspace(workspace)


if __name__ == "__main__":
    test_local_commit()
