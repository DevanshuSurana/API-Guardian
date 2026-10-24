
# ============================================================
# API Guardian - GitHub Service
# File: backend/services/github_service.py
#
# Purpose:
#   Communicates with the GitHub REST API to retrieve
#   information about repositories.
#
# Responsibilities:
#   - Send HTTP requests to GitHub
#   - Retrieve repository metadata
#   - Return relevant repository information
#
# Team: Member 2 - Backend & GitHub Integration
# ============================================================

import httpx

# Base URL for GitHub's REST API
GITHUB_API_URL = "https://api.github.com"


async def get_repository(owner: str, repo: str):
    """
    Retrieve information about a public GitHub repository.

    Args:
        owner (str): GitHub username or organization name.
        repo (str): Repository name.

    Returns:
        dict: Repository metadata including name, language,
              description, URL, and default branch.

    Raises:
        httpx.HTTPStatusError: If GitHub returns an HTTP error.
        httpx.RequestError: If the connection to GitHub fails.
    """

    # Construct the GitHub API URL for the repository
    url = f"{GITHUB_API_URL}/repos/{owner}/{repo}"

    # Set headers recommended by GitHub's REST API
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }

    # Create an asynchronous HTTP client
    async with httpx.AsyncClient(timeout=10.0) as client:

        # Send a GET request to GitHub
        response = await client.get(url, headers=headers)

        # Raise an exception if GitHub returns an error status
        response.raise_for_status()

        # Convert the JSON response into a Python dictionary
        data = response.json()

    # Return only the information needed by API Guardian
    return {
        "name": data["name"],
        "full_name": data["full_name"],
        "description": data["description"],
        "language": data["language"],
        "default_branch": data["default_branch"],
        "html_url": data["html_url"],
        "private": data["private"]
    }
