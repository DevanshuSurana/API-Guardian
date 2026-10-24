
# ============================================================
# API Guardian - Secure Publishing Tests
# File: backend/test_secure_publishing.py
#
# Purpose:
#   Confirm that remote publishing is blocked when
#   authorization or publishing configuration is missing.
# ============================================================

import os
from unittest.mock import patch

from services.github_publish_executor import (
    PublishingError,
    publish_migration_branch,
)


def test_unauthorized_push():
    """
    Verify that an unauthorized push is rejected
    before accessing the local Git repository.
    """

    try:
        publish_migration_branch(
            repository_path="/nonexistent/repository",
            repository_name="sneha0832/api-guardian-test-repo",
            branch_name="api-guardian/migration-test123",
            authorized=False,
        )
    except PublishingError:
        print("Unauthorized push correctly blocked.")
        return

    raise AssertionError(
        "Unauthorized push was not blocked."
    )


def test_disabled_publishing():
    """
    Verify that publishing remains disabled even
    when the internal authorization flag is True.
    """

    with patch.dict(
        os.environ,
        {"API_GUARDIAN_ENABLE_PUBLISH": "false"},
    ):
        try:
            publish_migration_branch(
                repository_path="/nonexistent/repository",
                repository_name="sneha0832/api-guardian-test-repo",
                branch_name="api-guardian/migration-test123",
                authorized=True,
            )
        except PublishingError:
            print("Disabled publishing correctly blocked.")
            return

    raise AssertionError(
        "Disabled publishing was not blocked."
    )


def test_unapproved_repository():
    """
    Verify that an unauthorized destination
    is rejected before any Git operation.
    """

    try:
        publish_migration_branch(
            repository_path="/nonexistent/repository",
            repository_name="DevanshuSurana/API-Guardian",
            branch_name="api-guardian/migration-test123",
            authorized=True,
        )
    except ValueError:
        print("Unapproved repository correctly blocked.")
        return

    raise AssertionError(
        "Unapproved repository was not blocked."
    )


if __name__ == "__main__":
    test_unauthorized_push()
    test_disabled_publishing()
    test_unapproved_repository()

    print("\nAll secure publishing tests passed!")
