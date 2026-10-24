
# ============================================================
# API Guardian - Migration Routes
# File: backend/routes/migrations.py
#
# Purpose:
#   Expose endpoints for AI-powered API migration analysis.
# ============================================================

from fastapi import APIRouter

from models.schemas import (
    MigrationRequest,
    MigrationResponse
)

from services.agent_service import analyze_migration

from models.schemas import (
    PatchPreviewRequest,
    PatchPreviewResponse,
)

from services.migration_service import preview_migration

from fastapi import HTTPException
from git.exc import GitCommandError
from models.schemas import BatchApplyResponse
from services.migration_service import apply_migration_batch
from services.patch_service import PatchError

from models.schemas import MigrationPrepareResponse
from services.migration_service import prepare_migration

from models.schemas import (
    PreparePullRequestRequest,
    PreparePullRequestResponse,
)

from services.migration_service import (
    prepare_migration_pull_request,
)

from models.schemas import (
    MigrationPlanRequest,
    MigrationPlanResponse,
)

from services.migration_service import create_migration_plan

from models.schemas import PublishDryRunResponse
from services.migration_service import prepare_publish_dry_run

from models.schemas import LocalCommitResponse
from services.migration_service import execute_local_migration_commit

# Group migration-related endpoints together
router = APIRouter(
    prefix="/api/migrations",
    tags=["Migrations"]
)


@router.post(
    "/analyze",
    response_model=MigrationResponse
)
async def analyze_api_migration(
    request: MigrationRequest
):
    """
    Receive API migration information and call the AI agent.

    Endpoint:
        POST /api/migrations/analyze

    Returns:
        A structured migration analysis response.
    """

    # Pass the validated request to the agent service
    result = await analyze_migration(request)

    # Return the agent's proposed changes
    return result


# ============================================================
# Endpoint: Preview API Migration
#
# POST /api/migrations/preview
#
# Purpose:
#   Clone a repository and preview proposed code changes.
#   Does not apply patches or push code to GitHub.
# ============================================================


@router.post(
    "/preview",
    response_model=PatchPreviewResponse,
)
def preview_api_migration(
    request: PatchPreviewRequest,
):
    """
    Preview proposed code changes against repository files.

    Returns a diff for each valid proposed modification.
    """

    try:
        return preview_migration(request)

    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error

    except GitCommandError as error:
        raise HTTPException(
            status_code=502,
            detail="Unable to clone the requested repository.",
        ) from error


# ============================================================
# Endpoint: Apply Batch Migration
#
# POST /api/migrations/apply
#
# Purpose:
#   Apply proposed changes to a temporary repository clone.
#
# Python: 3.10+
# Team: Member 2 - Backend & GitHub Integration
# ============================================================


@router.post(
    "/apply",
    response_model=BatchApplyResponse,
)
def apply_api_migration(
    request: PatchPreviewRequest,
):
    """
    Validate and apply proposed changes to a temporary clone.

    Does not commit, push, or modify the GitHub repository.
    """

    try:
        return apply_migration_batch(request)

    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error

    except PatchError as error:
        raise HTTPException(
            status_code=422,
            detail=str(error),
        ) from error

    except GitCommandError as error:
        raise HTTPException(
            status_code=502,
            detail="Unable to clone the requested repository.",
        ) from error


# ============================================================
# API Guardian - Prepare Migration Endpoint
#
# POST /api/migrations/prepare
#
# Purpose:
#   Prepare a Git branch and patched files locally,
#   returning the diff without writing to GitHub.
#
# Python: 3.10+
# Team: Member 2 - Backend & GitHub Integration
# ============================================================


@router.post(
    "/prepare",
    response_model=MigrationPrepareResponse,
)
def prepare_api_migration(
    request: PatchPreviewRequest,
):
    """
    Prepare a migration inside a temporary repository.

    Does not commit, push, or create a pull request.
    """

    try:
        return prepare_migration(request)

    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error

    except PatchError as error:
        raise HTTPException(
            status_code=422,
            detail=str(error),
        ) from error

    except GitCommandError as error:
        raise HTTPException(
            status_code=502,
            detail="Unable to prepare the Git repository.",
        ) from error


# ============================================================
# API Guardian - Prepare Pull Request Endpoint
# File: backend/routes/migrations.py
#
# Endpoint:
#   POST /api/migrations/prepare-pr
#
# Purpose:
#   Prepare local migration changes and return a draft
#   GitHub pull request payload without submitting it.
#
# Python: 3.10+
# Team: Member 2 - Backend & GitHub Integration
# ============================================================


@router.post(
    "/prepare-pr",
    response_model=PreparePullRequestResponse,
)
def prepare_pull_request_endpoint(
    request: PreparePullRequestRequest,
):
    """
    Prepare migration changes and PR metadata locally.
    """

    try:
        return prepare_migration_pull_request(request)

    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error

    except PatchError as error:
        raise HTTPException(
            status_code=422,
            detail=str(error),
        ) from error

    except GitCommandError as error:
        raise HTTPException(
            status_code=502,
            detail="Unable to prepare the Git repository.",
        ) from error


# ============================================================
# API Guardian - Complete Migration Plan Endpoint
# File: backend/routes/migrations.py
#
# Endpoint:
#   POST /api/migrations/plan
#
# Purpose:
#   Generate a complete migration plan without making
#   changes to the remote GitHub repository.
#
# Python: 3.10+
# Team: Member 2 - Backend & GitHub Integration
# ============================================================


@router.post(
    "/plan",
    response_model=MigrationPlanResponse,
)
def create_migration_plan_endpoint(
    request: MigrationPlanRequest,
):
    """
    Prepare a migration branch, code changes,
    commit plan, and draft PR payload.
    """

    try:
        return create_migration_plan(request)

    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error

    except PatchError as error:
        raise HTTPException(
            status_code=422,
            detail=str(error),
        ) from error

    except GitCommandError as error:
        raise HTTPException(
            status_code=502,
            detail="Unable to prepare the Git repository.",
        ) from error


# ============================================================
# API Guardian - GitHub Publishing Dry-Run Endpoint
# File: backend/routes/migrations.py
#
# Endpoint:
#   POST /api/migrations/publish/dry-run
#
# Purpose:
#   Preview Git commit, branch publishing, and draft
#   pull-request operations without executing them.
# ============================================================


@router.post(
    "/publish/dry-run",
    response_model=PublishDryRunResponse,
)
def publish_migration_dry_run(
    request: MigrationPlanRequest,
):
    """
    Prepare the complete publishing workflow
    without modifying GitHub.
    """

    try:
        return prepare_publish_dry_run(request)

    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error

    except PatchError as error:
        raise HTTPException(
            status_code=422,
            detail=str(error),
        ) from error

    except GitCommandError as error:
        raise HTTPException(
            status_code=502,
            detail="Unable to prepare the Git repository.",
        ) from error


# ============================================================
# API Guardian - Local Migration Commit Endpoint
# File: backend/routes/migrations.py
#
# Endpoint:
#   POST /api/migrations/commit/local
#
# Purpose:
#   Create a real Git commit inside a temporary clone.
# ============================================================


@router.post(
    "/commit/local",
    response_model=LocalCommitResponse,
)
def commit_migration_locally(
    request: MigrationPlanRequest,
):
    """
    Apply API migration patches and create a local commit.
    """

    try:
        return execute_local_migration_commit(request)

    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error

    except PatchError as error:
        raise HTTPException(
            status_code=422,
            detail=str(error),
        ) from error

    except GitCommandError as error:
        raise HTTPException(
            status_code=502,
            detail="Unable to complete the local Git operation.",
        ) from error
