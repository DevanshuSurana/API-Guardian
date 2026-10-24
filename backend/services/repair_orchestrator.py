
# ============================================================
# API Guardian - Self-Healing Repair Orchestrator
# File: backend/services/repair_orchestrator.py
#
# Purpose:
#   Validate AI-generated migrations and retry failed
#   migrations using an injected repair function.
# ============================================================

from typing import Callable

from models.schemas import FileChange

from services.code_validation_service import (
    validate_generated_python,
    CodeValidationError,
)
from services.repository_validation_service import (
    validate_repository_change,
)

MAX_ATTEMPTS = 3


def run_repair_loop(
    initial_change: FileChange,
    repair_function: Callable[[FileChange, str], FileChange],
    max_attempts: int = MAX_ATTEMPTS,
    repository_path: str | None = None,
) -> dict:
    """
    Validate an AI-generated migration.

    If validation fails, send the error to the repair
    function and retry.

    The repair function can be mocked for testing.

    No files are modified, committed, or pushed.
    """

    if max_attempts < 1:
        raise ValueError(
            "max_attempts must be at least 1."
        )

    current_change = initial_change
    history = []

    for attempt in range(1, max_attempts + 1):

        try:
            if repository_path is not None:
                validation = validate_repository_change(
                    repository_path=repository_path,
                    change=current_change,
                )

                if validation["status"] != "passed":
                    raise CodeValidationError(
                        validation.get(
                            "error",
                            "Repository validation failed.",
                        )
                    )
            else:
                validation = validate_generated_python(
                    source_code=current_change.updated_code,
                    file_path=current_change.file_path,
                )

            # Step 2: Record successful validation.
            history.append({
                "attempt": attempt,
                "status": "passed",
                "validation": validation,
            })

            # Step 3: Return the validated proposal.
            return {
                "status": "validated",
                "attempts": attempt,
                "change": current_change,
                "history": history,
            }

        except CodeValidationError as error:

            # Step 4: Record validation failure.
            error_message = str(error)

            history.append({
                "attempt": attempt,
                "status": "failed",
                "error": error_message,
            })

            # Step 5: Stop when retry limit is reached.
            if attempt == max_attempts:
                break

            # Step 6: Ask the repair agent for a new proposal.
            current_change = repair_function(
                current_change,
                error_message,
            )

            # Step 7: Prevent repair agent from changing
            # the target file or original source.
            if (
                current_change.file_path
                != initial_change.file_path
                or current_change.original_code
                != initial_change.original_code
            ):
                raise ValueError(
                    "Repair agent changed the original "
                    "file identity or source code."
                )

    return {
        "status": "failed",
        "attempts": len(history),
        "change": None,
        "history": history,
    }
