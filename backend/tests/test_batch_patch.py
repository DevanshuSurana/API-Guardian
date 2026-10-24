
# ============================================================
# API Guardian - Batch Patch Tests
# File: backend/test_batch_patch.py
#
# Purpose:
#   Verify that multiple patches can be applied together
#   and that invalid batches do not modify source files.
#
# ============================================================

import tempfile
from pathlib import Path

from models.schemas import FileChange
from services.batch_patch_service import apply_batch
from services.patch_service import PatchError


def test_batch_patching():
    """Test valid and invalid batches in a temporary workspace."""

    with tempfile.TemporaryDirectory() as workspace:

        repository = Path(workspace) / "repository"
        repository.mkdir()

        # Create two sample Python files.
        file_one = repository / "api_client.py"
        file_two = repository / "main.py"

        file_one.write_text(
            "client.old_method()\n",
            encoding="utf-8"
        )

        file_two.write_text(
            "api.old_request()\n",
            encoding="utf-8"
        )

        # Simulate two changes proposed by Member 1's agent.
        changes = [
            FileChange(
                file_path="api_client.py",
                original_code="client.old_method()",
                updated_code="client.new_method()",
                explanation="Update deprecated method."
            ),
            FileChange(
                file_path="main.py",
                original_code="api.old_request()",
                updated_code="api.new_request()",
                explanation="Update deprecated request."
            ),
        ]

        # Apply both changes.
        results = apply_batch(str(repository), changes)

        print("=== BATCH RESULTS ===")

        for result in results:
            print(result["file_path"], result["status"])
            print(result["diff"])

        # Verify both files were updated.
        assert file_one.read_text(
            encoding="utf-8"
        ) == "client.new_method()\n"

        assert file_two.read_text(
            encoding="utf-8"
        ) == "api.new_request()\n"

        print("Valid batch passed!")

        # Test an invalid batch.
        invalid_changes = [
            FileChange(
                file_path="api_client.py",
                original_code="client.new_method()",
                updated_code="client.latest_method()",
                explanation="Another migration."
            ),
            FileChange(
                file_path="missing.py",
                original_code="old()",
                updated_code="new()",
                explanation="Invalid target file."
            ),
        ]

        try:
            apply_batch(str(repository), invalid_changes)
            raise AssertionError(
                "Expected the invalid batch to fail."
            )

        except PatchError as error:
            print("Invalid batch rejected:", error)

        # Verify the first file was NOT partially modified.
        assert file_one.read_text(
            encoding="utf-8"
        ) == "client.new_method()\n"

        print("Atomic validation test passed!")


if __name__ == "__main__":
    test_batch_patching()
