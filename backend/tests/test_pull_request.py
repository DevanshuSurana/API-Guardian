
# ============================================================
# API Guardian - Pull Request Preparation Test
# File: backend/test_pull_request.py
#
# Purpose:
#   Test GitHub PR payload generation without making
#   network requests or modifying any repository.
#
# Python: 3.10+
# ============================================================

import json

from services.pull_request_service import (
    build_pull_request_payload,
)


def test_pull_request_payload():
    """Verify that a valid migration produces a PR payload."""

    branch_name = "api-guardian/migration-abc123"

    changed_files = [
        "api_client.py",
        "checkout.py",
    ]

    summary = (
        "Replace deprecated PaymentClient.old_charge() "
        "calls with PaymentClient.new_charge()."
    )

    # Generate the GitHub pull request payload.
    payload = build_pull_request_payload(
        branch_name=branch_name,
        changed_files=changed_files,
        summary=summary,
        base_branch="main",
    )

    print("=== GENERATED PULL REQUEST ===")
    print(json.dumps(payload, indent=2))

    # Verify the required GitHub fields.
    assert payload["head"] == branch_name
    assert payload["base"] == "main"
    assert payload["draft"] is True

    # Verify both modified files appear in the description.
    assert "api_client.py" in payload["body"]
    assert "checkout.py" in payload["body"]

    print("\nPull request preparation test passed!")


def test_invalid_pull_request():
    """Verify that an empty change list is rejected."""

    try:
        build_pull_request_payload(
            branch_name="api-guardian/migration-abc123",
            changed_files=[],
            summary="Update deprecated API methods.",
        )

    except ValueError as error:
        print("\nInvalid PR correctly rejected:", error)
        return

    raise AssertionError(
        "Expected empty changed files to be rejected."
    )


if __name__ == "__main__":
    test_pull_request_payload()
    test_invalid_pull_request()
