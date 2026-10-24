
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

from api_agent import generate_migration


def analyze_file_with_ai(
    changelog: str,
    file_path: str,
    source_code: str,
) -> FileChange | None:
    """
    Analyze a source file using Member 1's AI agent.

    Returns FileChange when a modification is proposed.
    Returns None when the file is unaffected or unchanged.

    Does not modify any repository files.
    """

    # Step 4: Run the AI agent.
    result = generate_migration(
        changelog,
        source_code,
    )

    # Step 5: Check whether the file is affected.
    if not result["affected"]:
        return None

    # Step 6: Get the AI-generated code.
    updated_code = result["updated_code"]

    # Step 7: Skip unchanged code.
    if updated_code == source_code:
        return None

    # Step 8: Convert the AI output to our backend schema.
    return FileChange(
        file_path=file_path,
        original_code=source_code,
        updated_code=updated_code,
        explanation=result["explanation"],
    )
