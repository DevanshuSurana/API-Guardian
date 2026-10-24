
import tempfile
from pathlib import Path

import pytest

from models.schemas import FileChange
from services.ai_repair_integration import run_ai_repair


changelog = """
Payment API v2:
process_payment(amount) has been removed.
Use create_payment(amount) instead.
"""

original_code = """from payment_api import process_payment

def checkout():
    return process_payment(100)
"""

broken_code = """def checkout():
    return create_payment(100)
"""


@pytest.mark.integration
def test_ai_repository_repair():
    with tempfile.TemporaryDirectory() as directory:
        repository = Path(directory)
        checkout_file = repository / "checkout.py"

        checkout_file.write_text(
            original_code,
            encoding="utf-8",
        )

        initial_change = FileChange(
            file_path="checkout.py",
            original_code=original_code,
            updated_code=broken_code,
            explanation="Migrate to the new payment API.",
        )

        print("Starting repository-aware AI repair...")

        result = run_ai_repair(
            changelog=changelog,
            initial_change=initial_change,
            repository_path=str(repository),
        )

        print("\nFinal status:", result["status"])
        print("Attempts:", result["attempts"])

        for attempt in result["history"]:
            print(
                f"Attempt {attempt['attempt']}: "
                f"{attempt['status']}"
            )
            if "error" in attempt:
                print("  Error:", attempt["error"])

        assert result["status"] == "validated"
        assert result["attempts"] >= 2

        repaired_change = result["change"]
        assert repaired_change is not None

        print("\nAI-repaired code:")
        print(repaired_change.updated_code)

        # The repair must preserve the target file identity.
        assert repaired_change.file_path == "checkout.py"
        assert repaired_change.original_code == original_code

        # Validation must not modify the repository.
        assert checkout_file.read_text(
            encoding="utf-8"
        ) == original_code

        print("\nPASS: Repository-aware AI repair works!")
        print("PASS: Original repository remains unchanged!")


if __name__ == "__main__":
    test_ai_repository_repair()
