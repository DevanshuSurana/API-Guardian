
# ============================================================
# API Guardian - Git Commit Preparation Service
# File: backend/services/git_commit_service.py
#
# Purpose:
#   Prepare a Git commit plan for validated API migrations.
#
#   This service does NOT stage files, create commits,
#   push branches, or modify GitHub repositories.
#
# Python: 3.10+
# Team: Member 2 - Backend & GitHub Integration
# ============================================================

from pathlib import Path
from typing import Any

from git import Repo, InvalidGitRepositoryError

from services.patch_service import validate_file_path
from git import GitCommandError

def prepare_git_commit(
    repository_path: str,
    changed_files: list[str],
    commit_message: str = "fix: migrate deprecated API usage",
) -> dict[str, Any]:
    """
    Prepare metadata for a future Git commit.

    Args:
        repository_path: Local cloned Git repository.
        changed_files: Files modified by API Guardian.
        commit_message: Proposed Git commit message.

    Returns:
        Dictionary describing the proposed commit.

    No Git changes are performed.
    """

    # Step 1: Verify the repository exists.
    repository = Repo(repository_path)

    if repository.bare:
        raise ValueError(
            "Cannot prepare a commit in a bare repository."
        )

    # Step 2: Validate the commit message.
    if not commit_message.strip():
        raise ValueError(
            "Commit message cannot be empty."
        )

    # Step 3: Require at least one changed file.
    if not changed_files:
        raise ValueError(
            "Cannot prepare a commit without changed files."
        )

    # Step 4: Validate that all requested files exist
    # inside the repository and are safe to access.
    validated_files = []

    for file_path in changed_files:
        target = validate_file_path(
            repository_path,
            file_path,
        )

        # Convert the validated path into a repository-relative path.
        relative_path = target.relative_to(
            Path(repository_path).resolve()
        ).as_posix()

        if relative_path not in validated_files:
            validated_files.append(relative_path)

    # Step 5: Identify actual tracked modifications.
    modified_files = set(
        repository.git.diff("--name-only").splitlines()
    )

    # Only include files with real working-tree changes.
    files_to_commit = [
        file_path
        for file_path in validated_files
        if file_path in modified_files
    ]

    if not files_to_commit:
        raise ValueError(
            "No modified tracked files found to commit."
        )

    # Step 6: Generate a diff for the selected files.
    diff = repository.git.diff(
        "--",
        *files_to_commit,
    )

    # Step 7: Return a commit plan without performing it.
    return {
        "branch_name": repository.active_branch.name,
        "commit_message": commit_message.strip(),
        "files": files_to_commit,
        "total_files": len(files_to_commit),
        "diff": diff,
        "status": "commit_plan_prepared",
    }

# ============================================================
# API Guardian - Local Git Commit Execution
# File: backend/services/git_commit_service.py
#
# Purpose:
#   Stage and commit validated migration changes inside
#   a temporary Git repository.
# ============================================================


def create_local_migration_commit(
    repository_path: str,
    changed_files: list[str],
    commit_message: str,
) -> dict:
    """
    Create a Git commit containing only approved file changes.

    The repository must already be on a migration branch.
    No remote Git operations are performed.
    """

    # Step 1: Reuse the Phase 16 validation logic.
    commit_plan = prepare_git_commit(
        repository_path=repository_path,
        changed_files=changed_files,
        commit_message=commit_message,
    )

    repository = Repo(repository_path)

    # Step 2: Verify that we are on a migration branch.
    branch_name = repository.active_branch.name

    if not branch_name.startswith("api-guardian/migration-"):
        raise ValueError(
            "Commits are only allowed on API Guardian migration branches."
        )

    # Step 3: Require a clean staging area.
    # This prevents unrelated staged files from entering the commit.
    if repository.git.diff("--cached", "--name-only").strip():
        raise ValueError(
            "Cannot commit: the Git staging area is not empty."
        )

    # Step 4: Stage only the validated files.
    files_to_commit = commit_plan["files"]

    repository.git.add("--", *files_to_commit)

    
    # Step 5: Create a real Git commit locally.
    # Use GitPython's execute() to pass Git command arguments.
    # This does not push anything to GitHub.

    repository.git.execute([
        "git",
        "-c", "user.name=API Guardian",
        "-c", "user.email=api-guardian@users.noreply.github.com",
        "-c", "core.hooksPath=/dev/null",
        "commit",
        "-m", commit_message.strip(),
        "--only",
        "--",
        *files_to_commit,
    ])


    # Step 6: Read the newly created commit.
    commit = repository.head.commit

    # Step 7: Verify the files actually included in the commit.
    committed_files = sorted(
        commit.stats.files.keys()
    )

    expected_files = sorted(files_to_commit)

    if committed_files != expected_files:
        raise RuntimeError(
            "Committed files do not match the validated migration files."
        )

    # Step 8: Return commit metadata.
    return {
        "branch_name": branch_name,
        "commit_hash": commit.hexsha,
        "short_commit_hash": commit.hexsha[:7],
        "commit_message": commit.message.strip(),
        "committed_files": committed_files,
        "total_committed_files": len(committed_files),
        "status": "committed_locally",
    }
