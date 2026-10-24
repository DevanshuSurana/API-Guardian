
# ============================================================
# API Guardian - GitHub Authentication Service
# File: backend/services/github_auth_service.py
#
# Purpose:
#   Securely load GitHub credentials from environment
#   variables and verify GitHub authentication.
#
# Python: 3.10+
# Team: Member 2 - Backend & GitHub Integration
# ============================================================

import os
from pathlib import Path

import httpx
from dotenv import load_dotenv


# Locate backend/.env regardless of where Python is run.
ENV_PATH = Path(__file__).resolve().parents[1] / ".env"

# Load environment variables from the .env file.
load_dotenv(dotenv_path=ENV_PATH)


def get_github_token() -> str:
    """
    Retrieve the GitHub access token from the environment.
    """

    token = os.getenv("GITHUB_TOKEN", "").strip()

    if not token:
        raise ValueError(
            "GITHUB_TOKEN is missing. Configure backend/.env."
        )

    return token


async def verify_github_auth() -> dict:
    """
    Verify the GitHub token using a read-only API request.
    """

    token = get_github_token()

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(
            "https://api.github.com/user",
            headers=headers,
        )

        response.raise_for_status()

        user = response.json()

        return {
            "login": user["login"],
            "account_id": user["id"],
            "authenticated": True,
        }
