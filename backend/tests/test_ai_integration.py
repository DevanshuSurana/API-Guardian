
from services.ai_integration_service import analyze_file_with_ai

changelog = """
Payment API v2:
process_payment(amount) has been removed.
Use create_payment(amount) instead.
"""

source_code = """
from payment_api import process_payment

def checkout():
    return process_payment(100)
"""

print("Running AI migration analysis...")

result = analyze_file_with_ai(
    changelog=changelog,
    file_path="checkout.py",
    source_code=source_code,
)

if result is None:
    print("No changes proposed.")
else:
    print("\nAffected file:", result.file_path)
    print("\nOriginal code:")
    print(result.original_code)
    print("\nUpdated code:")
    print(result.updated_code)
    print("\nExplanation:")
    print(result.explanation)
