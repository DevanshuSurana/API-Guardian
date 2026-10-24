
# ============================================================
# API Guardian - Repository Routes
# File: backend/routes/repositories.py
#
# Purpose:
#   Defines API endpoints for interacting with GitHub
#   repositories through the API Guardian backend.
#
# Responsibilities:
#   - Handle incoming repository requests
#   - Call the GitHub service
#   - Return repository information as JSON
#   - Handle GitHub API errors
# ============================================================

import httpx

from fastapi import APIRouter, HTTPException
from services.github_service import get_repository


# Create a router for repository-related endpoints
router = APIRouter(
    prefix="/api/repositories",
    tags=["Repositories"]
)


@router.get("/{owner}/{repo}")
async def repository_details(owner: str, repo: str):
    """
    Retrieve information about a GitHub repository.

    Endpoint:
        GET /api/repositories/{owner}/{repo}

    Example:
        GET /api/repositories/fastapi/fastapi

    Args:
        owner (str): GitHub username or organization.
        repo (str): Repository name.

    Returns:
        dict: Repository information returned by GitHub.
    """

    try:
        # Call the GitHub service to retrieve repository data
        repository = await get_repository(owner, repo)

        # Return the repository information as JSON
        return repository

    except httpx.HTTPStatusError as error:

        # Extract the HTTP status code returned by GitHub
        status = error.response.status_code

        # Repository does not exist or is not publicly accessible
        if status == 404:
            raise HTTPException(
                status_code=404,
                detail="GitHub repository not found"
            ) from error

        # GitHub denied access or the API rate limit was reached
        if status == 403:
            raise HTTPException(
                status_code=403,
                detail="GitHub API access denied or rate limited"
            ) from error

        # Handle any other error returned by GitHub
        raise HTTPException(
            status_code=502,
            detail="GitHub API returned an error"
        ) from error

    except httpx.RequestError as error:

        # Handle network issues, timeouts, or connection failures
        raise HTTPException(
            status_code=502,
            detail="Could not connect to GitHub"
        ) from error
