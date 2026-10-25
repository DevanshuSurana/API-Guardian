# ============================================================
# API Guardian - GitHub Publishing Executor
# File: backend/services/github_publish_executor.py
#
# Purpose:
#   Publish a validated migration branch and create a
#   draft pull request in an explicitly approved repository.
# ============================================================

import base64
import os
import re
import subprocess
from pathlib import Path

import httpx
from git import Repo

from services.github_auth_service import get_github_token
from services.github_publish_service import validate_publish_target


class PublishingError(Exception):
    """Raised when GitHub publishing fails."""


def validate_publishing_request(
    repository_name: str,
    branch_name: str,
    base_branch: str,
) -> None:
    """Validate repository and branch restrictions."""

    validate_publish_target(repository_name)

    if not re.fullmatch(
        r"api-guardian/migration-[a-zA-Z0-9_-]+",
        branch_name,
    ):
        raise PublishingError("Invalid migration branch.")

    if not re.fullmatch(
        r"[a-zA-Z0-9][a-zA-Z0-9/_-]*",
        base_branch,
    ):
        raise PublishingError("Invalid base branch.")

    if branch_name == base_branch:
        raise PublishingError("Migration branch cannot equal base branch.")


def _require_repository_push_access(repository_name: str, token: str) -> None:
    """Fail early with an actionable message if the token's account is read-only."""
    url = f"https://api.github.com/repos/{repository_name}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    try:
        response = httpx.get(url, headers=headers, timeout=15.0)
    except httpx.HTTPError:
        raise PublishingError(
            "Could not verify GitHub repository write access. Check the network "
            "connection and try again."
        ) from None

    if response.status_code != 200:
        raise PublishingError(
            "Could not verify GitHub repository access "
            f"(HTTP {response.status_code}). Check that the token can access "
            "this repository and read its metadata."
        )

    permissions = response.json().get("permissions") or {}
    if permissions.get("push") is False:
        raise PublishingError(
            f"The configured GitHub account does not have write access to "
            f"{repository_name}. Ask the repository owner to grant it Write "
            "access, accept the invitation, then prepare a fresh review."
        )


# ============================================================
# API Guardian - Secure GitHub Branch Publishing
# File: backend/services/github_publish_executor.py
#
# Purpose:
#   Publish an approved migration branch using GitHub
#   credentials without embedding the token in the
#   remote URL or Git command-line arguments.
#
# Safety:
#   Publishing is disabled unless explicitly authorized.
# ============================================================


def publish_migration_branch(
    repository_path: str,
    repository_name: str,
    branch_name: str,
    *,
    authorized: bool = False,
) -> dict:
    """
    Push a migration branch to an approved GitHub repository.

    This function performs a remote write only when all
    authorization and configuration checks pass.
    """

    # Step 1: Validate the approved repository.
    validate_publish_target(repository_name)

    # Step 2: Validate migration branch naming.
    if not re.fullmatch(
        r"api-guardian/migration-[a-zA-Z0-9_-]+",
        branch_name,
    ):
        raise PublishingError("Invalid migration branch.")

    # Step 3: Require explicit internal authorization.
    if not authorized:
        raise PublishingError("Publishing requires explicit authorization.")

    # Step 4: Require the server-side publishing switch.
    if os.getenv("API_GUARDIAN_ENABLE_PUBLISH") != "true":
        raise PublishingError("GitHub publishing is disabled.")

    # Step 5: Verify the local repository.
    repository = Repo(repository_path)

    if repository.active_branch.name != branch_name:
        raise PublishingError("Active branch does not match migration branch.")

    if repository.is_dirty(untracked_files=True):
        raise PublishingError("Repository contains uncommitted changes.")

    # Step 6: Verify the configured remote destination.
    expected_remote = f"https://github.com/{repository_name}.git"

    actual_remote = repository.remotes.origin.url

    if actual_remote.rstrip("/").removesuffix(".git") != (
        expected_remote.removesuffix(".git")
    ):
        raise PublishingError("Git remote does not match approved repository.")

    # Step 7: Obtain the GitHub token.
    token = get_github_token()

    # Confirm the authenticated account can push before creating a local commit.
    _require_repository_push_access(repository_name, token)

    # Step 8: Build the authentication header.
    credentials = base64.b64encode(f"x-access-token:{token}".encode()).decode(
        "ascii"
    )

    auth_header = f"AUTHORIZATION: basic {credentials}"

    # Step 9: Supply the credential through the environment.
    # This avoids embedding it in the command-line arguments.
    environment = os.environ.copy()

    environment["GIT_CONFIG_COUNT"] = "2"
    environment["GIT_CONFIG_KEY_0"] = "http.extraheader"
    environment["GIT_CONFIG_VALUE_0"] = auth_header
    environment["GIT_CONFIG_KEY_1"] = "credential.helper"
    environment["GIT_CONFIG_VALUE_1"] = ""

    environment["GIT_TERMINAL_PROMPT"] = "0"
    environment["GIT_ASKPASS"] = "/bin/false"

    # Step 10: Push only the migration branch.
    command = [
        "git",
        "-C",
        str(Path(repository_path).resolve()),
        "push",
        "origin",
        f"HEAD:refs/heads/{branch_name}",
    ]

    try:
        subprocess.run(
            command,
            env=environment,
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        )

    except subprocess.CalledProcessError:
        # Do not expose Git stderr because it may contain
        # sensitive authentication or repository details.
        raise PublishingError("GitHub rejected the migration branch push.") from None

    except subprocess.TimeoutExpired:
        raise PublishingError("GitHub branch publishing timed out.") from None

    return {
        "repository": repository_name,
        "branch_name": branch_name,
        "status": "branch_published",
    }


async def create_draft_pull_request(
    repository_name: str,
    payload: dict,
    *,
    authorized: bool = False,
) -> dict:
    """Create a draft PR using the GitHub REST API."""

    validate_publish_target(repository_name)

    if not authorized:
        raise PublishingError("Pull request creation requires authorization.")

    if os.getenv("API_GUARDIAN_ENABLE_PUBLISH") != "true":
        raise PublishingError("GitHub publishing is disabled.")

    if payload.get("draft") is not True:
        raise PublishingError("Only draft pull requests are allowed.")

    validate_publishing_request(
        repository_name,
        payload.get("head", ""),
        payload.get("base", ""),
    )

    token = get_github_token()

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    url = f"https://api.github.com/repos/{repository_name}/pulls"

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            url,
            headers=headers,
            json=payload,
        )

    if response.status_code not in (200, 201):
        raise PublishingError(
            f"GitHub rejected PR creation: HTTP {response.status_code}"
        )

    data = response.json()

    return {
        "repository": repository_name,
        "pull_request_number": data["number"],
        "pull_request_url": data["html_url"],
        "status": "draft_pr_created",
    }
