# ============================================================
# API Guardian - Git Branch Service
# File: backend/services/git_branch_service.py
#
# Purpose:
#   Create local migration branches and generate Git diffs
#   for AI-generated code changes.
#
#   No remote pushes or GitHub PRs are performed.
#
# Python: 3.10+
# Team: Member 2 - Backend & GitHub Integration
# ============================================================

import re
from uuid import uuid4

from git import Repo


def create_migration_branch(
    repository_path: str,
    branch_name: str | None = None,
) -> str:
    """
    Create and switch to a new local migration branch.

    Each branch receives a unique name to avoid conflicts.
    """

    repository = Repo(repository_path)

    # Generate a unique branch name unless a review workflow supplied one.
    branch_name = branch_name or f"api-guardian/migration-{uuid4().hex[:12]}"
    if not re.fullmatch(r"api-guardian/migration-[a-zA-Z0-9_-]+", branch_name):
        raise ValueError("Invalid API Guardian migration branch name.")

    # Create the branch from the cloned repository's HEAD.
    repository.git.checkout("-b", branch_name)

    return branch_name


def generate_git_diff(repository_path: str) -> str:
    """
    Generate the Git diff for modified tracked files.

    Does not commit or push changes.
    """

    repository = Repo(repository_path)

    # Compare working tree changes against the current index.
    return repository.git.diff()


def get_changed_files(repository_path: str) -> list[str]:
    """
    Return tracked files modified in the working directory.

    Does not include untracked files.
    """

    repository = Repo(repository_path)

    # Identify modified tracked files.
    return repository.git.diff("--name-only").splitlines()
