
# ============================================================
# API Guardian - GitHub Permissions Test
# File: backend/test_github_permissions.py
#
# Purpose:
#   Test permission evaluation using simulated GitHub
#   responses without a GitHub token or network access.
#
# Python: 3.10+
# ============================================================

from services.github_permissions_service import (
    evaluate_repository_permissions,
)


def test_repository_permissions():
    """Test writable, read-only, and unknown permissions."""

    # Case 1: Repository with push access.
    writable = {
        "full_name": "example/api-test",
        "permissions": {
            "pull": True,
            "push": True,
            "admin": False,
        },
    }

    result = evaluate_repository_permissions(writable)

    print("=== WRITABLE REPOSITORY ===")
    print(result)

    assert result["can_read"] is True
    assert result["can_push"] is True
    assert result["can_prepare_pull_request"] is True

    # Case 2: Repository with read-only access.
    readonly = {
        "full_name": "example/read-only",
        "permissions": {
            "pull": True,
            "push": False,
            "admin": False,
        },
    }

    result = evaluate_repository_permissions(readonly)

    print("\n=== READ-ONLY REPOSITORY ===")
    print(result)

    assert result["can_read"] is True
    assert result["can_push"] is False
    assert result["can_prepare_pull_request"] is False

    # Case 3: Permissions not provided.
    unknown = {
        "full_name": "example/unknown",
    }

    result = evaluate_repository_permissions(unknown)

    print("\n=== UNKNOWN PERMISSIONS ===")
    print(result)

    assert result["can_read"] is False
    assert result["can_push"] is False
    assert result["can_prepare_pull_request"] is False

    print("\nGitHub permissions test passed!")


if __name__ == "__main__":
    test_repository_permissions()
