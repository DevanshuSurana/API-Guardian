
"""Validate AI-generated patches against complete repository files."""

from pathlib import Path

from models.schemas import FileChange
from services.patch_service import prepare_patch, PatchError
from services.code_validation_service import (
    validate_generated_python,
    CodeValidationError,
)


def validate_repository_change(
    repository_path: str,
    change: FileChange,
) -> dict:
    """
    Validate a proposed change against the actual repository file.

    Does not modify repository files or execute generated code.
    """

    try:
        # Validate path and construct the complete updated file.
        target, original_content, updated_content = prepare_patch(
            repository_path,
            change,
        )

        # Run static checks against the complete updated file.
        if target.suffix == ".py":
            validation = validate_generated_python(
                source_code=updated_content,
                file_path=change.file_path,
            )
        else:
            validation = {
                "status": "skipped",
                "reason": "Python validation not applicable",
            }

        return {
            "status": "passed",
            "file_path": change.file_path,
            "original_size": len(original_content),
            "updated_size": len(updated_content),
            "validation": validation,
        }

    except (PatchError, CodeValidationError) as error:
        return {
            "status": "failed",
            "file_path": change.file_path,
            "error": str(error),
        }
