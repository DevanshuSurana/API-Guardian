
# ============================================================
# API Guardian - Patch Service Test
# File: backend/test_patch_service.py
#
# Purpose:
#   Test patch previewing and application using a temporary
#   directory without changing a real GitHub repository.
#
# Python: 3.10+
# ============================================================

import tempfile
from pathlib import Path

from models.schemas import FileChange
from services.patch_service import generate_diff, apply_patch


def test_patch():
    """Create a temporary file and test a proposed API fix."""

    # TemporaryDirectory automatically cleans up after the test.
    with tempfile.TemporaryDirectory() as workspace:

        repository = Path(workspace) / "repository"
        repository.mkdir()

        # Create a sample source code file.
        source_file = repository / "example.py"

        source_file.write_text(
            'client.old_api_call(value="test")\n',
            encoding="utf-8"
        )

        # Simulate the AI agent's proposed change.
        change = FileChange(
            file_path="example.py",
            original_code='client.old_api_call(value="test")',
            updated_code='client.new_api_call(value="test")',
            explanation="Replace the deprecated API method."
        )

        # Preview the change.
        diff = generate_diff(str(repository), change)

        print("=== PATCH PREVIEW ===")
        print(diff)

        # Apply the change to the temporary file.
        modified_file = apply_patch(str(repository), change)

        print("=== MODIFIED FILE ===")
        print(Path(modified_file).read_text(encoding="utf-8"))

        # Verify the expected result.
        assert (
            source_file.read_text(encoding="utf-8")
            == 'client.new_api_call(value="test")\n'
        )

        print("Patch test passed!")


if __name__ == "__main__":
    test_patch()
