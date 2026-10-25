"""Manual Ollama integration demo for one Python source file."""

from services.ai_integration_service import analyze_file_with_ai


def main() -> None:
    changelog = """
    Payment API v2:
    process_payment(amount) has been removed.
    Use create_payment(amount) instead.
    """
    source_code = """from payment_api import process_payment

def checkout():
    return process_payment(100)
"""

    result = analyze_file_with_ai(
        changelog=changelog,
        file_path="checkout.py",
        source_code=source_code,
    )
    if result is None:
        print("No changes proposed.")
        return

    print("Affected file:", result.file_path)
    print("\nOriginal code:\n", result.original_code)
    print("\nUpdated code:\n", result.updated_code)
    print("\nExplanation:\n", result.explanation)


if __name__ == "__main__":
    main()
