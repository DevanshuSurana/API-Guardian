"""Manual Ollama demo for a breaking changelog and unaffected source file."""

from api_agent import generate_migration


def main() -> None:
    changelog = """
    Version 2.0:
    The payment API create_charge(amount, currency) was removed.
    Use create_payment(amount_minor_units, currency_code) instead.
    """

    source_code = 'def greet(name):\n    return f"Hello, {name}!"\n'

    result = generate_migration(changelog, source_code)
    print("Breaking change:", result["breaking_change"])
    print("Affected:", result["affected"])
    print("Affected usages:", result["affected_usages"])
    print("Code unchanged:", result["updated_code"] == source_code)
    print("\nFull report:")
    print(result)

    assert result["breaking_change"] is True
    assert result["affected"] is False
    assert result["affected_usages"] == []
    assert result["updated_code"] == source_code


if __name__ == "__main__":
    main()
