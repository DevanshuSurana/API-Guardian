
# ============================================================
# API Guardian - Patch Service
# File: backend/services/patch_service.py
#
# Purpose:
#   Validate AI-generated code changes, preview differences,
#   and apply approved patches to temporary repository files.
# ============================================================

import ast
import difflib
from pathlib import Path

from models.schemas import FileChange


class PatchError(Exception):
    """Raised when a proposed patch cannot be applied safely."""


def validate_file_path(
    repository_path: str,
    file_path: str
) -> Path:
    """
    Resolve a file path inside a cloned repository.

    Reject:
      - Absolute paths
      - Parent-directory traversal
      - Symlinks
      - Files outside the repository
      - Nonexistent files
    """

    repository = Path(repository_path).resolve(strict=True)
    relative_path = Path(file_path)

    if relative_path.is_absolute():
        raise PatchError("Absolute file paths are not allowed.")

    if not relative_path.parts or ".." in relative_path.parts:
        raise PatchError("Invalid file path.")

    # Check each existing path component for symlinks.
    current = repository

    for part in relative_path.parts:
        current = current / part

        if current.is_symlink():
            raise PatchError("Symbolic links are not allowed.")

    # Resolve the proposed target path.
    # Resolve the path and handle missing files gracefully.
    try:
        target = current.resolve(strict=True)

    except (FileNotFoundError, NotADirectoryError) as error:
        raise PatchError(
            f"Target file does not exist: {file_path}"
        ) from error

    # Confirm that the file is inside the repository.
    if not target.is_relative_to(repository):
        raise PatchError("File is outside the repository.")

    if not target.is_file():
        raise PatchError("Target is not a regular file.")

    return target


def prepare_patch(
    repository_path: str,
    change: FileChange
) -> tuple[Path, str, str]:
    """
    Validate a proposed change and prepare its new contents.

    The original code must appear exactly once to avoid
    replacing an unintended occurrence.
    """

    target = validate_file_path(
        repository_path,
        change.file_path
    )

    # Read the existing source code.
    try:
        original_content = target.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise PatchError(
            "Unable to read the target as a UTF-8 source file."
        ) from error

    if not change.original_code:
        raise PatchError("Original code cannot be empty.")

    # Count how often the original code appears.
    occurrences = original_content.count(change.original_code)

    if occurrences == 0:
        raise PatchError(
            "Original code was not found in the file."
        )

    if occurrences > 1:
        raise PatchError(
            "Original code appears multiple times."
        )

    # Replace only the verified occurrence.
    updated_content = original_content.replace(
        change.original_code,
        change.updated_code,
        1
    )

    # Validate Python syntax before accepting the patch.
    validate_python_syntax(
        change.file_path,
        updated_content
    )

    return target, original_content, updated_content



def validate_python_syntax(
    file_path: str,
    updated_content: str
) -> None:
    """
    Validate the syntax of AI-generated Python code.

    This does not execute the code.
    """

    if not file_path.endswith(".py"):
        return

    try:
        ast.parse(
            updated_content,
            filename=file_path
        )
    except SyntaxError as error:
        raise PatchError(
            f"Invalid Python syntax in {file_path}: "
            f"{error.msg} at line {error.lineno}"
        ) from error


def generate_diff(
    repository_path: str,
    change: FileChange
) -> str:
    """
    Generate a unified diff without modifying the file.
    """

    _, original_content, updated_content = prepare_patch(
        repository_path,
        change
    )

    diff = difflib.unified_diff(
        original_content.splitlines(keepends=True),
        updated_content.splitlines(keepends=True),
        fromfile=f"a/{change.file_path}",
        tofile=f"b/{change.file_path}"
    )

    return "".join(diff)


def apply_patch(
    repository_path: str,
    change: FileChange
) -> str:
    """
    Apply a validated change to a local repository file.

    Only call this on an isolated temporary workspace.
    """

    target, _, updated_content = prepare_patch(
        repository_path,
        change
    )

    try:
        target.write_text(
            updated_content,
            encoding="utf-8"
        )
    except OSError as error:
        raise PatchError("Unable to write patched file.") from error

    return str(target)
