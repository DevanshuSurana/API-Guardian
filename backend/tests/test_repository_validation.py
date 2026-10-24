
import tempfile
from pathlib import Path

from models.schemas import FileChange
from services.repository_validation_service import (
    validate_repository_change,
)


with tempfile.TemporaryDirectory() as directory:

    # Simulate a repository.
    repository = Path(directory)
    file_path = repository / "checkout.py"

    original_code = """from payment_api import process_payment

def checkout():
    return process_payment(100)
"""

    file_path.write_text(original_code, encoding="utf-8")

    # First attempt: missing import.
    broken_change = FileChange(
        file_path="checkout.py",
        original_code=original_code,
        updated_code="""def checkout():
    return create_payment(100)
""",
        explanation="Replace removed payment API.",
    )

    broken_result = validate_repository_change(
        str(repository),
        broken_change,
    )

    print("Broken migration:", broken_result["status"])
    print("Error:", broken_result.get("error"))

    assert broken_result["status"] == "failed"

    # Second attempt: corrected migration.
    corrected_change = FileChange(
        file_path="checkout.py",
        original_code=original_code,
        updated_code="""from payment_api import create_payment

def checkout():
    return create_payment(100)
""",
        explanation="Replace API and update import.",
    )

    corrected_result = validate_repository_change(
        str(repository),
        corrected_change,
    )

    print("\nCorrected migration:", corrected_result["status"])

    assert corrected_result["status"] == "passed"

    # Ensure validation did not modify the repository.
    assert file_path.read_text(encoding="utf-8") == original_code

    print("Repository file unchanged: PASS")
    print("\nPASS: Complete-file validation works!")
