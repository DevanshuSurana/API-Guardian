
from services.patch_service import (
    PatchError,
    validate_python_syntax,
)

# Valid Python
valid_code = """
from payment_api import create_payment

def checkout():
    return create_payment(100)
"""

# Invalid Python
invalid_code = """
def checkout(
    return create_payment(100)
"""

print("Testing valid Python...")

validate_python_syntax("checkout.py", valid_code)
print("PASS: Valid Python accepted")

print("\nTesting invalid Python...")

try:
    validate_python_syntax("checkout.py", invalid_code)
except PatchError as error:
    print("PASS: Invalid Python rejected")
    print("Reason:", error)
else:
    raise AssertionError(
        "FAIL: Invalid Python was accepted"
    )
