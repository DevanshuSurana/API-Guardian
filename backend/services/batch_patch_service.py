
# ============================================================
# API Guardian - Batch Patch Service
# File: backend/services/batch_patch_service.py
#
# Purpose:
#   Validate and apply multiple proposed code changes
#   to files in a local temporary repository workspace.
#
#   If validation fails, no files are modified.
#
# Python: 3.10+
# Team: Member 2 - Backend & GitHub Integration
# ============================================================

import difflib
from pathlib import Path

from models.schemas import FileChange
from services.patch_service import PatchError, prepare_patch


def prepare_batch(
    repository_path: str,
    changes: list[FileChange]
) -> list[dict]:
    """
    Validate all proposed patches before modifying files.

    Reject duplicate target files to prevent conflicting edits.
    """

    if not changes:
        raise PatchError("At least one change is required.")

    prepared = []
    seen_files = set()

    for change in changes:

        # Validate the file and the original code.
        target, original, updated = prepare_patch(
            repository_path,
            change
        )

        # Reject multiple changes to the same physical file.
        if target in seen_files:
            raise PatchError(
                f"Conflicting changes for {change.file_path}"
            )

        seen_files.add(target)

        # Generate a preview of the proposed modification.
        diff = "".join(
            difflib.unified_diff(
                original.splitlines(keepends=True),
                updated.splitlines(keepends=True),
                fromfile=f"a/{change.file_path}",
                tofile=f"b/{change.file_path}",
            )
        )

        prepared.append({
            "file_path": change.file_path,
            "target": target,
            "original": original,
            "updated": updated,
            "diff": diff,
        })

    return prepared


def apply_batch(
    repository_path: str,
    changes: list[FileChange]
) -> list[dict]:
    """
    Validate all patches, then apply them.

    If writing a file fails, attempt to restore files
    that were already modified.

    This is a prototype rollback mechanism, not a
    crash-safe transaction. Use isolated workspaces.
    """

    # All validation happens before the first write.
    prepared = prepare_batch(repository_path, changes)

    modified = []

    try:
        for item in prepared:

            target: Path = item["target"]

            # Detect changes made after validation.
            current = target.read_text(encoding="utf-8")

            if current != item["original"]:
                raise PatchError(
                    f"File changed during patching: "
                    f"{item['file_path']}"
                )

            # Save the target before attempting a write,
            # so rollback can restore it if writing fails.
            modified.append(item)

            target.write_text(
                item["updated"],
                encoding="utf-8"
            )

    except (OSError, UnicodeError, PatchError) as error:

        rollback_errors = []

        # Attempt to restore all files touched by this batch.
        for item in reversed(modified):
            try:
                item["target"].write_text(
                    item["original"],
                    encoding="utf-8"
                )
            except OSError as rollback_error:
                rollback_errors.append(str(rollback_error))

        if rollback_errors:
            raise PatchError(
                "Patch failed and rollback was incomplete: "
                + "; ".join(rollback_errors)
            ) from error

        raise PatchError(
            f"Batch application failed: {error}"
        ) from error

    return [
        {
            "file_path": item["file_path"],
            "diff": item["diff"],
            "status": "applied",
        }
        for item in prepared
    ]
