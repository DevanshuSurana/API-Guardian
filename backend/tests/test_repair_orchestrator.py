
from models.schemas import FileChange

from services.repair_orchestrator import run_repair_loop


# AI-generated code with a missing import.
initial_change = FileChange(
    file_path="checkout.py",
    original_code=(
        "from payment_api import process_payment\n\n"
        "def checkout():\n"
        "    return process_payment(100)\n"
    ),
    updated_code=(
        "def checkout():\n"
        "    return create_payment(100)\n"
    ),
    explanation="Replace the removed payment API.",
)


def mock_repair(change: FileChange, error: str) -> FileChange:
    """
    Simulate Member 1's future AI repair agent.
    """

    print("\nRepair agent received error:")
    print(error)

    return FileChange(
        file_path=change.file_path,
        original_code=change.original_code,
        updated_code=(
            "from payment_api import create_payment\n\n"
            "def checkout():\n"
            "    return create_payment(100)\n"
        ),
        explanation="Added the missing import.",
    )


result = run_repair_loop(
    initial_change=initial_change,
    repair_function=mock_repair,
)

print("\nFinal status:", result["status"])
print("Total attempts:", result["attempts"])

for attempt in result["history"]:
    print(
        f"Attempt {attempt['attempt']}: "
        f"{attempt['status']}"
    )

assert result["status"] == "validated"
assert result["attempts"] == 2

print("\nPASS: Self-healing retry loop works!")
