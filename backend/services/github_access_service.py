
# ============================================================
# API Guardian - GitHub Access Service
# File: backend/services/github_access_service.py
#
# Purpose:
#   Retrieve real GitHub repository metadata and evaluate
#   the authenticated user's repository permissions.
#
#   All requests are read-only.
#
# Python: 3.10+
# Team: Member 2 - Backend & GitHub Integration
# ============================================================

import httpx

from services.github_auth_service import get_github_token
from services.github_permissions_service import (
    evaluate_repository_permissions,
)


async def check_repository_access(
    owner: str,
    repo: str,
) -> dict:
    """
    Check the authenticated account's repository access.

    Calls GitHub's read-only GET /repos/{owner}/{repo}.
    """

    # Retrieve the token from the environment.
    token = get_github_token()

    # Configure the authenticated GitHub API request.
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(
            f"https://api.github.com/repos/{owner}/{repo}",
            headers=headers,
        )

        # Raise an error for invalid credentials,
        # inaccessible repositories, or other HTTP errors.
        response.raise_for_status()

        repository_data = response.json()

    # Reuse our Phase 12 permission evaluator.
    permissions = evaluate_repository_permissions(
        repository_data
    )

    # Return only the fields needed by the backend.
    return {
        **permissions,
        "private": repository_data.get("private"),
        "default_branch": repository_data.get("default_branch"),
    }
