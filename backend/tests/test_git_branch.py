
# ============================================================
# API Guardian - Git Branch Service Test
# File: backend/test_git_branch.py
#
# Purpose:
#   Verify local migration branch creation and Git diffs.
# ============================================================

import tempfile
from pathlib import Path

from git import Repo

from models.schemas import FileChange
from services.batch_patch_service import apply_batch
from services.git_branch_service import (
    create_migration_branch,
    generate_git_diff,
    get_changed_files,
)


def test_git_branch():
    """
    Create a temporary Git repository, patch a file,
    and inspect the resulting branch and Git diff.
    """

    with tempfile.TemporaryDirectory() as workspace:

        # Step 1: Create a temporary repository.
        repository_path = Path(workspace) / "repository"
        repository_path.mkdir()

        repository = Repo.init(repository_path)

        # Step 2: Create an example source file.
        source_file = repository_path / "api_client.py"

        source_file.write_text(
            "client.old_method()\n",
            encoding="utf-8"
        )

        # Step 3: Commit the original file locally.
        # This creates a baseline for Git diff.
        repository.index.add(["api_client.py"])

        repository.index.commit(
            "Initial test commit"
        )

        # Step 4: Create a migration branch.
        branch_name = create_migration_branch(
            str(repository_path)
        )

        print("Created branch:", branch_name)

        # Step 5: Simulate an AI-generated patch.
        changes = [
            FileChange(
                file_path="api_client.py",
                original_code="client.old_method()",
                updated_code="client.new_method()",
                explanation="Update deprecated API method."
            )
        ]

        # Step 6: Apply the patch to the temporary repository.
        apply_batch(
            str(repository_path),
            changes
        )

        # Step 7: Generate the Git diff.
        diff = generate_git_diff(
            str(repository_path)
        )

        changed_files = get_changed_files(
            str(repository_path)
        )

        print("\n=== GIT DIFF ===")
        print(diff)

        print("\n=== CHANGED FILES ===")
        print(changed_files)

        # Step 8: Verify the branch and modified file.
        assert repository.active_branch.name == branch_name
        assert "api_client.py" in changed_files
        assert "-client.old_method()" in diff
        assert "+client.new_method()" in diff

        print("\nGit branch test passed!")


if __name__ == "__main__":
    test_git_branch()
