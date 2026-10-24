
# ============================================================
# API Guardian - GitHub Repository Access Test
# File: backend/test_github_access.py
#
# Purpose:
#   Test authenticated, read-only access to a real
#   GitHub repository.
#
# ============================================================

import asyncio

import httpx

from services.github_access_service import (
    check_repository_access,
)


async def main():
    """Test real GitHub repository access."""

    # Replace this with your GitHub username.
    owner = "sneha0832"

    # Name of your separate test repository.
    repo = "api-guardian-test-repo"

    try:
        result = await check_repository_access(
            owner,
            repo,
        )

        print("=== GITHUB REPOSITORY ACCESS ===")

        for key, value in result.items():
            print(f"{key}: {value}")

        print("\nGitHub access test passed!")

    except ValueError as error:
        print("Configuration error:", error)

    except httpx.HTTPStatusError as error:
        print(
            "GitHub API error:",
            error.response.status_code,
        )

    except httpx.RequestError as error:
        print("Connection error:", error)


if __name__ == "__main__":
    asyncio.run(main())
