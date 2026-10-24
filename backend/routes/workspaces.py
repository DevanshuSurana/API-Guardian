
# ============================================================
# API Guardian - Workspace Routes
# File: backend/routes/workspaces.py
#
# Purpose:
#   Provide API endpoints for cloning and inspecting
#   GitHub repositories.
#
# Responsibilities:
#   - Receive repository scan requests
#   - Clone public repositories
#   - Return supported source file paths
#   - Clean up temporary files
#
# Team: Member 2 - Backend & GitHub Integration
# ============================================================

from fastapi import APIRouter, HTTPException

from git import GitCommandError

from services.repository_service import (
    clone_repository,
    list_source_files,
    cleanup_workspace
)


# Create a router for workspace-related operations
router = APIRouter(
    prefix="/api/workspaces",
    tags=["Workspaces"]
)


@router.post("/scan/{owner}/{repo}")
def scan_repository(owner: str, repo: str):
    """
    Clone a public repository and list its source files.

    Endpoint:
        POST /api/workspaces/scan/{owner}/{repo}

    Example:
        POST /api/workspaces/scan/fastapi/fastapi

    Returns:
        dict: Repository name, file count, and source file paths.
    """

    workspace = None

    try:
        # Clone the repository into a temporary workspace
        workspace, repository_path = clone_repository(
            owner,
            repo
        )

        # Find source files supported by API Guardian
        source_files = list_source_files(repository_path)

        # Return the scan results to the client
        return {
            "repository": f"{owner}/{repo}",
            "total_files": len(source_files),
            "files": source_files,
            "status": "scan_complete"
        }

    except ValueError as error:
        # Invalid repository owner or repository name
        raise HTTPException(
            status_code=400,
            detail=str(error)
        ) from error

    except GitCommandError as error:
        # Git failed to clone the requested repository
        raise HTTPException(
            status_code=502,
            detail="Unable to clone GitHub repository"
        ) from error

    finally:
        # Always delete the temporary workspace
        if workspace is not None:
            cleanup_workspace(workspace)
