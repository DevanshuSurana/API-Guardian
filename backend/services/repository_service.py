
# ============================================================
# API Guardian - Repository Management Service
# File: backend/services/repository_service.py
#
# Purpose:
#   Clone public GitHub repositories into temporary folders
#   and retrieve their source files.
#
# Responsibilities:
#   - Validate GitHub repository names
#   - Clone repositories into temporary workspaces
#   - List supported source code files
#   - Clean up temporary workspaces
#
# Team: Member 2 - Backend & GitHub Integration
# ============================================================

import re
import shutil
import tempfile
from pathlib import Path

from git import Repo, GitCommandError


# Supported source code extensions for initial scanning
SUPPORTED_EXTENSIONS = {
    ".py",
    ".js",
    ".ts",
    ".java",
    ".jsx",
    ".tsx"
}

# Limit the amount of source code returned by the API
MAX_FILES = 200

# GitHub owner/repository names should be simple path segments
OWNER_PATTERN = re.compile(r"^[A-Za-z0-9-]{1,39}$")
REPO_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,100}$")


def validate_repository(owner: str, repo: str):
    """
    Validate the repository owner and name.

    This prevents arbitrary paths or unexpected URL components
    from being passed to Git.
    """

    if not OWNER_PATTERN.fullmatch(owner):
        raise ValueError("Invalid GitHub owner name")

    if not REPO_PATTERN.fullmatch(repo):
        raise ValueError("Invalid GitHub repository name")

    if repo in {".", ".."}:
        raise ValueError("Invalid repository name")


def clone_repository(owner: str, repo: str):
    """
    Clone a public GitHub repository into a temporary folder.

    Args:
        owner (str): GitHub username or organization.
        repo (str): GitHub repository name.

    Returns:
        tuple: (workspace_path, repository_path)

    Raises:
        ValueError: If the repository name is invalid.
        GitCommandError: If Git fails to clone the repository.
    """

    # Validate the user-provided repository information
    validate_repository(owner, repo)

    # Construct the HTTPS URL for the public repository
    repo_url = f"https://github.com/{owner}/{repo}.git"

    # Create a unique temporary workspace
    workspace = Path(
        tempfile.mkdtemp(prefix="api_guardian_")
    )

    # Repository will be cloned inside this folder
    repository_path = workspace / "repository"

    try:
        # Clone only the latest commit to reduce download time
        # Disable interactive Git prompts
        Repo.clone_from(
            repo_url,
            str(repository_path),
            depth=1,
            env={"GIT_TERMINAL_PROMPT": "0"}
        )

        return workspace, repository_path

    except Exception:
        # Delete the workspace if cloning fails
        shutil.rmtree(workspace, ignore_errors=True)
        raise


def list_source_files(repository_path: Path):
    """
    Find supported source code files in a repository.

    Args:
        repository_path (Path): Local cloned repository path.

    Returns:
        list: Relative paths of supported source files.
    """

    source_files = []

    # Directories that should not be scanned
    excluded_directories = {
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        "dist",
        "build"
    }

    # Recursively search through repository files
    for file_path in repository_path.rglob("*"):

        # Stop once the file limit has been reached
        if len(source_files) >= MAX_FILES:
            break

        # Skip directories and symbolic links
        if not file_path.is_file() or file_path.is_symlink():
            continue

        # Determine the path relative to the repository root
        relative_path = file_path.relative_to(repository_path)

        # Skip excluded directories
        if any(
            part in excluded_directories
            for part in relative_path.parts
        ):
            continue

        # Include only supported programming languages
        if file_path.suffix.lower() in SUPPORTED_EXTENSIONS:
            source_files.append(str(relative_path))

    # Sort results to make the response easier to read
    return sorted(source_files)


def cleanup_workspace(workspace: Path):
    """
    Delete a temporary repository workspace.

    Args:
        workspace (Path): Temporary workspace to delete.
    """

    # Remove the temporary directory and its contents
    shutil.rmtree(workspace, ignore_errors=True)
