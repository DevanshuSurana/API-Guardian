
"""Connect the backend repair loop to the Ollama AI repair agent."""

import sys
from pathlib import Path

from models.schemas import FileChange
from services.repair_orchestrator import run_repair_loop

PROJECT_ROOT = Path(__file__).resolve().parents[2]
AI_AGENT_DIRECTORY = PROJECT_ROOT / "ai_agent"

if not (AI_AGENT_DIRECTORY / "repair_agent.py").is_file():
    raise ImportError("AI repair agent not found.")

if str(AI_AGENT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(AI_AGENT_DIRECTORY))

from repair_agent import repair_migration


def run_ai_repair(
    changelog: str,
    initial_change: FileChange,
    repository_path: str | None = None,
) -> dict:
    """
    Run the real AI-powered repair loop.

    The backend validates code and Ollama repairs failed proposals.

    No files are modified or published.
    """

    def repair_with_ollama(
        current_change: FileChange,
        validation_error: str,
    ) -> FileChange:

        result = repair_migration(
            changelog=changelog,
            original_code=current_change.original_code,
            previous_code=current_change.updated_code,
            validation_errors=validation_error,
        )

        return FileChange(
            file_path=current_change.file_path,
            original_code=current_change.original_code,
            updated_code=result["updated_code"],
            explanation=result["explanation"],
        )

    return run_repair_loop(
    initial_change=initial_change,
    repair_function=repair_with_ollama,
    max_attempts=3,
    repository_path=repository_path,
    )
