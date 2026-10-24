
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

initial_change = FileChange(
    file_path="checkout.py",
    original_code=original_code,
    updated_code=broken_code,
    explanation="Replace the removed payment API.",
)

print("Starting real AI self-healing test...")

result = run_ai_repair(
    changelog=changelog,
    initial_change=initial_change,
)

print("\nFinal status:", result["status"])
print("Total attempts:", result["attempts"])

for attempt in result["history"]:
    print(
        f"Attempt {attempt['attempt']}: "
        f"{attempt['status']}"
    )
    if "error" in attempt:
        print("  Error:", attempt["error"])

if result["change"] is not None:
    print("\nFinal AI-generated code:")
    print(result["change"].updated_code)

assert result["status"] == "validated"
assert result["attempts"] >= 2

print("\nPASS: Ollama repaired the migration!")
