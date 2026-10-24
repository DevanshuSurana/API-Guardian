
from api_agent import generate_migration

changelog = """
Version 2.0:
The payment API create_charge(amount, currency) was removed.
Use create_payment(amount_minor_units, currency_code) instead.
"""

source_code = """
def greet(name):
    return f"Hello, {name}!"
"""

result = generate_migration(changelog, source_code)

print("Breaking change:", result["breaking_change"])
print("Affected:", result["affected"])
print("Affected usages:", result["affected_usages"])
print("Code unchanged:", result["updated_code"] == source_code)
print("\nFull report:")
print(result)
