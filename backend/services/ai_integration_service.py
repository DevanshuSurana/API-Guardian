
# ============================================================
# API Guardian - AI Integration Service
# File: backend/services/ai_integration_service.py
#
# Purpose:
#   Connect Member 1's AI agent with Member 2's backend.
# ============================================================

import sys
from pathlib import Path

from models.schemas import FileChange

# Step 1: Locate the project root.
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Step 2: Locate Member 1's AI agent.
AGENT_DIRECTORY = PROJECT_ROOT / "ai_agent"

if not (AGENT_DIRECTORY / "api_agent.py").is_file():
    raise ImportError(
        f"AI agent not found in {AGENT_DIRECTORY}"
    )

# Step 3: Make the AI agent importable.
sys.path.insert(0, str(AGENT_DIRECTORY))

from api_agent import (
    audit_api_source,
    generate_migration,
)
from api_agent import (
    has_candidate_api_usage as _has_candidate_api_usage,
)


def has_candidate_api_usage(source_code: str, changelog: str) -> bool | None:
    """Expose the agent's static Python usage prefilter to the scanner."""
    return _has_candidate_api_usage(source_code, changelog)


def audit_source_for_api_issues(
    source_code: str,
    file_path: str,
    dependency_context: str,
) -> dict:
    """Run the local-model automatic API audit for one source file."""
    return audit_api_source(source_code, file_path, dependency_context)


def analyze_source_with_ai(
    changelog: str,
    file_path: str,
    source_code: str,
) -> tuple[bool, FileChange | None]:
    """
    Analyze a source file and preserve the breaking-change classification.

    Returns (breaking_change, FileChange). The FileChange is None if the
    source file is unaffected or the model proposes no change.

    Does not modify any repository files.
    """

    # Step 4: Run the AI agent.
    try:
        result = generate_migration(
            changelog,
            source_code,
        )
    except ValueError as error:
        # Distinguish invalid model output from invalid HTTP request input so
        # the route reports an AI service failure (503), not a client error.
        raise RuntimeError(
            "The AI agent could not produce a safe migration after its retry: "
            f"{error}. Ambiguous edits are rejected rather than guessed; try "
            "narrowing the changelog to the specific API usage."
        ) from error

    # Step 5: Check whether the file is affected.
    if not result["affected"]:
        return result["breaking_change"], None

    # Step 6: Get the AI-generated code.
    updated_code = result["updated_code"]

    # Step 7: Skip unchanged code.
    if updated_code == source_code:
        return result["breaking_change"], None

    # Step 8: Convert the AI output to our backend schema.
    change = FileChange(
        file_path=file_path,
        original_code=source_code,
        updated_code=updated_code,
        explanation=result["explanation"],
    )
    return result["breaking_change"], change


def analyze_file_with_ai(
    changelog: str,
    file_path: str,
    source_code: str,
) -> FileChange | None:
    """Compatibility wrapper returning only a proposed file change."""
    _, change = analyze_source_with_ai(changelog, file_path, source_code)
    return change
