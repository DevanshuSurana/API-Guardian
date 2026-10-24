
# ============================================================
# API Guardian - Publishing Integration Tests
# File: backend/test_publishing_integration.py
#
# Purpose:
#   Verify remote publishing remains blocked and that
#   the migration planning workflow works end to end.

# ============================================================

import asyncio

import pytest

from models.schemas import MigrationPlanRequest, FileChange
from services.migration_service import (
    prepare_publish_dry_run,
    execute_github_migration,
)
from services.github_publish_executor import PublishingError


def build_test_request():
    """Create a test migration request."""

    return MigrationPlanRequest(
        owner="sneha0832",
        repo="api-guardian-test-repo",
        summary="Replace deprecated payment API calls.",
        base_branch="main",
        commit_message="fix: migrate deprecated payment API",
        changes=[
            FileChange(
                file_path="api_client.py",
                original_code="client.old_charge(100)",
                updated_code="client.new_charge(100)",
                explanation="Replace deprecated API.",
            ),
            FileChange(
                file_path="checkout.py",
                original_code="client.old_charge(amount)",
                updated_code="client.new_charge(amount)",
                explanation="Update checkout API.",
            ),
        ],
    )


@pytest.mark.integration
async def test_unauthorized_publishing():
    """Ensure unauthorized publishing is rejected."""

    request = build_test_request()

    try:
        await execute_github_migration(
            request,
            authorized=False,
        )
    except PublishingError:
        print("Unauthorized publishing correctly blocked.")
        return

    raise AssertionError(
        "Unauthorized publishing was not blocked."
    )


@pytest.mark.integration
def test_complete_dry_run():
    """Verify the complete planning workflow."""

    request = build_test_request()

    result = prepare_publish_dry_run(request)

    assert result.status == "dry_run_only"
    assert result.remote_writes_enabled is False
    assert len(result.changed_files) == 2
    assert len(result.operations) == 3

    print("Complete migration dry run passed.")


async def main():
    await test_unauthorized_publishing()
    test_complete_dry_run()

    print("\nPublishing integration tests passed!")


if __name__ == "__main__":
    asyncio.run(main())
