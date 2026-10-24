"""Coordinate repository scanning with the local AI migration agent."""

from __future__ import annotations

import asyncio

from models.schemas import FileChange, MigrationRequest, MigrationResponse

from services.ai_integration_service import analyze_source_with_ai
from services.repository_service import (
    cleanup_workspace,
    clone_repository,
    list_source_files,
)

# Keep local-model latency and prompt size bounded for the initial integration.
MAX_AI_ANALYSIS_FILES = 20
MAX_AI_ANALYSIS_FILE_BYTES = 128 * 1024


def _analyze_repository(request: MigrationRequest) -> MigrationResponse:
    workspace, repository_path = clone_repository(request.owner, request.repo)
    try:
        source_files = list_source_files(repository_path)
        files_to_analyze = source_files[:MAX_AI_ANALYSIS_FILES]
        skipped_files = max(0, len(source_files) - len(files_to_analyze))
        analyzed_files = 0
        breaking_change = False
        affected_files: list[FileChange] = []

        for relative_path in files_to_analyze:
            source_path = repository_path / relative_path
            try:
                if source_path.stat().st_size > MAX_AI_ANALYSIS_FILE_BYTES:
                    skipped_files += 1
                    continue
                source_code = source_path.read_text(
                    encoding="utf-8",
                    errors="replace",
                )
            except OSError:
                skipped_files += 1
                continue

            if not source_code.strip():
                continue

            analyzed_files += 1
            file_breaking, change = analyze_source_with_ai(
                changelog=request.changelog,
                file_path=relative_path,
                source_code=source_code,
            )
            breaking_change = breaking_change or file_breaking
            if change is not None:
                affected_files.append(change)

        summary = (
            f"Analyzed {analyzed_files} source files; "
            f"proposed changes for {len(affected_files)} affected files."
        )
        if skipped_files:
            summary += f" Skipped {skipped_files} files due to scan limits."

        return MigrationResponse(
            repository=f"{request.owner}/{request.repo}",
            breaking_change=breaking_change,
            affected_files=affected_files,
            summary=summary,
            status="analysis_limited" if skipped_files else "analysis_complete",
        )
    finally:
        cleanup_workspace(workspace)


async def analyze_migration(request: MigrationRequest) -> MigrationResponse:
    """Clone and analyze a public repository without modifying it."""
    return await asyncio.to_thread(_analyze_repository, request)
