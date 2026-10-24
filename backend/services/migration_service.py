
# ============================================================
# API Guardian - Migration Orchestration Service
# File: backend/services/migration_service.py
#
# Purpose:
#   Connect repository cloning with patch validation
#   and diff generation.
#
#   This service previews changes only.
#   It never modifies GitHub repositories.
#
# Python: 3.10+
# Team: Member 2 - Backend & GitHub Integration
# ============================================================
import os
from models.schemas import (
    PatchPreviewRequest,
    PatchPreviewResponse,
    PatchPreviewResult,
)

from services.repository_service import (
    clone_repository,
    cleanup_workspace,
)

from services.patch_service import (
    generate_diff,
    PatchError,
)

from models.schemas import BatchApplyResponse, AppliedFileResult
from services.batch_patch_service import apply_batch

from models.schemas import MigrationPrepareResponse

from services.git_branch_service import (
    create_migration_branch,
    generate_git_diff,
    get_changed_files,
)

from models.schemas import (
    PreparePullRequestRequest,
    PreparePullRequestResponse,
)

from services.pull_request_service import (
    build_pull_request_payload,
)

from models.schemas import (
    MigrationPlanRequest,
    MigrationPlanResponse,
)

from services.git_commit_service import prepare_git_commit
from services.git_branch_service import (
    create_migration_branch,
    generate_git_diff,
    get_changed_files,
)
from services.pull_request_service import build_pull_request_payload

from models.schemas import PublishDryRunResponse
from services.github_publish_service import (
    build_publish_plan,
    validate_publish_target,
)

from models.schemas import LocalCommitResponse

from services.git_commit_service import (
    create_local_migration_commit,
)

from services.github_publish_executor import (
    publish_migration_branch,
    create_draft_pull_request,
    PublishingError,
)

def preview_migration(
    request: PatchPreviewRequest,
) -> PatchPreviewResponse:
    """
    Clone a repository and preview AI-proposed changes.

    The temporary workspace is always deleted afterward.
    """

    workspace = None
    results = []

    try:
        # Step 1: Clone the GitHub repository.
        workspace, repository_path = clone_repository(
            request.owner,
            request.repo,
        )

        # Step 2: Validate each proposed change.
        for change in request.changes:

            try:
                # Generate a diff without modifying the file.
                diff = generate_diff(
                    str(repository_path),
                    change,
                )

                results.append(
                    PatchPreviewResult(
                        file_path=change.file_path,
                        valid=True,
                        diff=diff,
                    )
                )

            except (PatchError, OSError, UnicodeError) as error:
                # Record the failure without stopping other previews.
                results.append(
                    PatchPreviewResult(
                        file_path=change.file_path,
                        valid=False,
                        error=str(error),
                    )
                )

        # Step 3: Count successfully validated changes.
        valid_count = sum(
            1 for result in results if result.valid
        )

        # Step 4: Return the preview summary.
        return PatchPreviewResponse(
            repository=f"{request.owner}/{request.repo}",
            total_changes=len(request.changes),
            valid_changes=valid_count,
            results=results,
            status="preview_complete",
        )

    finally:
        # Step 5: Remove the temporary cloned repository.
        if workspace is not None:
            cleanup_workspace(workspace)



# ============================================================
# Batch Migration Application
#
# Purpose:
#   Clone a public GitHub repository, apply a validated batch
#   of patches locally, and return the results.
#
# No Git commits, pushes, or pull requests are performed.
# ============================================================


def apply_migration_batch(
    request: PatchPreviewRequest,
) -> BatchApplyResponse:
    """
    Apply multiple proposed changes to a temporary clone.

    The cloned workspace is automatically removed after
    processing, whether the operation succeeds or fails.
    """

    workspace = None

    try:
        # Step 1: Clone the requested repository.
        workspace, repository_path = clone_repository(
            request.owner,
            request.repo,
        )

        # Step 2: Validate and apply the entire batch.
        # apply_batch raises PatchError for invalid changes.
        applied = apply_batch(
            str(repository_path),
            request.changes,
        )

        # Step 3: Convert service results into response models.
        results = [
            AppliedFileResult(
                file_path=item["file_path"],
                diff=item["diff"],
                status=item["status"],
            )
            for item in applied
        ]

        # Step 4: Return a summary of the local changes.
        return BatchApplyResponse(
            repository=f"{request.owner}/{request.repo}",
            total_changes=len(request.changes),
            applied_changes=len(results),
            results=results,
            status="applied_to_temporary_workspace",
        )

    finally:
        # Step 5: Always delete the temporary clone.
        if workspace is not None:
            cleanup_workspace(workspace)


# ============================================================
# API Guardian - Migration Preparation Service
# File: backend/services/migration_service.py
#
# Purpose:
#   Coordinate repository cloning, local branch creation,
#   patch application, and Git diff generation.
#
# Python: 3.10+
# Team: Member 2 - Backend & GitHub Integration
# ============================================================


def prepare_migration(
    request: PatchPreviewRequest,
) -> MigrationPrepareResponse:
    """
    Prepare proposed API changes on a temporary Git branch.

    This function does not commit or push changes.
    The workspace is deleted when processing finishes.
    """

    workspace = None

    try:
        # Step 1: Clone the requested GitHub repository.
        workspace, repository_path = clone_repository(
            request.owner,
            request.repo,
        )

        # Step 2: Create a dedicated local migration branch.
        branch_name = create_migration_branch(
            str(repository_path)
        )

        # Step 3: Validate and apply all proposed patches.
        # An invalid patch raises PatchError.
        apply_batch(
            str(repository_path),
            request.changes,
        )

        # Step 4: Generate the Git diff.
        diff = generate_git_diff(
            str(repository_path)
        )

        # Step 5: Identify modified tracked files.
        changed_files = get_changed_files(
            str(repository_path)
        )

        # Step 6: Return the preparation results.
        return MigrationPrepareResponse(
            repository=f"{request.owner}/{request.repo}",
            branch_name=branch_name,
            changed_files=changed_files,
            total_changed_files=len(changed_files),
            diff=diff,
            status="prepared_locally",
        )

    finally:
        # Step 7: Delete the temporary repository.
        # This also removes the temporary migration branch.
        if workspace is not None:
            cleanup_workspace(workspace)


# ============================================================
# API Guardian - Prepare Pull Request Workflow
# File: backend/services/migration_service.py
#
# Purpose:
#   Combine migration preparation with GitHub PR payload
#   generation, without modifying remote repositories.
#
# Python: 3.10+
# Team: Member 2 - Backend & GitHub Integration
# ============================================================


def prepare_migration_pull_request(
    request: PreparePullRequestRequest,
) -> PreparePullRequestResponse:
    """
    Prepare migration changes and a draft PR payload.

    The migration branch exists only in a temporary clone.
    No commits, pushes, or GitHub PRs are created.
    """

    # Validate the PR metadata before cloning.
    # Use a placeholder migration branch for validation.
    build_pull_request_payload(
        branch_name="api-guardian/migration-validation",
        changed_files=[change.file_path for change in request.changes],
        summary=request.summary,
        base_branch=request.base_branch,
    )

    # Reuse the existing Phase 10 migration workflow.
    migration = prepare_migration(request)

    # Generate the GitHub-compatible PR payload.
    pr_payload = build_pull_request_payload(
        branch_name=migration.branch_name,
        changed_files=migration.changed_files,
        summary=request.summary,
        base_branch=request.base_branch,
    )

    return PreparePullRequestResponse(
        repository=migration.repository,
        branch_name=migration.branch_name,
        changed_files=migration.changed_files,
        total_changed_files=migration.total_changed_files,
        diff=migration.diff,
        pull_request=pr_payload,
        status="pr_payload_prepared_locally",
    )


# ============================================================
# API Guardian - Complete Migration Planning Service
# File: backend/services/migration_service.py
#
# Purpose:
#   Generate a complete migration plan containing a local
#   branch, applied patches, Git diff, commit metadata,
#   and draft pull request metadata.
#
# Python: 3.10+
# Team: Member 2 - Backend & GitHub Integration
# ============================================================


def create_migration_plan(
    request: MigrationPlanRequest,
) -> MigrationPlanResponse:
    """
    Prepare a complete API migration plan.

    All changes are made in a temporary clone.
    No commits, pushes, or pull requests are created.
    """

    # Step 1: Validate PR metadata before cloning.
    build_pull_request_payload(
        branch_name="api-guardian/migration-validation",
        changed_files=[
            change.file_path for change in request.changes
        ],
        summary=request.summary,
        base_branch=request.base_branch,
    )

    # Step 2: Validate commit message before cloning.
    if not request.commit_message.strip():
        raise ValueError(
            "Commit message cannot be empty."
        )

    workspace = None

    try:
        # Step 3: Clone the GitHub repository.
        workspace, repository_path = clone_repository(
            request.owner,
            request.repo,
        )

        # Step 4: Create a local migration branch.
        branch_name = create_migration_branch(
            str(repository_path)
        )

        # Step 5: Validate and apply proposed changes.
        apply_batch(
            str(repository_path),
            request.changes,
        )

        # Step 6: Generate the Git diff.
        diff = generate_git_diff(
            str(repository_path)
        )

        # Step 7: Identify modified tracked files.
        changed_files = get_changed_files(
            str(repository_path)
        )

        # Step 8: Prepare commit metadata while the
        # temporary repository still exists.
        commit_plan = prepare_git_commit(
            repository_path=str(repository_path),
            changed_files=changed_files,
            commit_message=request.commit_message,
        )

        # Step 9: Build a draft GitHub PR payload.
        pull_request = build_pull_request_payload(
            branch_name=branch_name,
            changed_files=commit_plan["files"],
            summary=request.summary,
            base_branch=request.base_branch,
        )

        # Step 10: Return the complete migration plan.
        return MigrationPlanResponse(
            repository=f"{request.owner}/{request.repo}",
            branch_name=branch_name,
            changed_files=commit_plan["files"],
            total_changed_files=commit_plan["total_files"],
            diff=diff,
            commit_plan=commit_plan,
            pull_request=pull_request,
            status="migration_plan_prepared",
        )

    finally:
        # Step 11: Delete the temporary repository,
        # including the temporary migration branch.
        if workspace is not None:
            cleanup_workspace(workspace)


# ============================================================
# API Guardian - Publishing Dry-Run Orchestration
# File: backend/services/migration_service.py
#
# Purpose:
#   Combine the complete migration plan with a safe
#   GitHub publishing plan.
#
# Python: 3.10+
# Team: Member 2 - Backend & GitHub Integration
# ============================================================


def prepare_publish_dry_run(
    request: MigrationPlanRequest,
) -> PublishDryRunResponse:
    """
    Generate a complete migration and publishing plan.

    This function does not create Git commits,
    push branches, or open pull requests.
    """

    # Step 1: Reject unapproved repositories before cloning.
    repository_name = f"{request.owner}/{request.repo}"

    validate_publish_target(repository_name)

    # Step 2: Generate the complete migration plan.
    migration = create_migration_plan(request)

    # Step 3: Generate the GitHub publishing dry-run plan.
    publishing = build_publish_plan(migration)

    # Step 4: Combine both results into one response.
    return PublishDryRunResponse(
        repository=migration.repository,
        branch_name=migration.branch_name,
        migration_status=migration.status,
        changed_files=migration.changed_files,
        diff=migration.diff,
        commit_plan=migration.commit_plan,
        pull_request=migration.pull_request,
        operations=publishing["operations"],
        remote_writes_enabled=publishing["remote_writes_enabled"],
        status=publishing["status"],
    )


# ============================================================
# API Guardian - Local Commit Orchestration
# File: backend/services/migration_service.py
#
# Purpose:
#   Clone an approved repository, apply validated API
#   changes, create a local Git commit, and return
#   commit and draft PR metadata.
# ============================================================


def execute_local_migration_commit(
    request: MigrationPlanRequest,
) -> LocalCommitResponse:
    """
    Execute the API migration in a temporary Git clone.

    Creates a real local commit, but never pushes to GitHub.
    """

    repository_name = f"{request.owner}/{request.repo}"

    # Step 1: Restrict the target to the approved test repo.
    validate_publish_target(repository_name)

    # Step 2: Validate PR metadata before cloning.
    build_pull_request_payload(
        branch_name="api-guardian/migration-validation",
        changed_files=[
            change.file_path for change in request.changes
        ],
        summary=request.summary,
        base_branch=request.base_branch,
    )

    # Step 3: Validate the commit message.
    if not request.commit_message.strip():
        raise ValueError(
            "Commit message cannot be empty."
        )

    workspace = None

    try:
        # Step 4: Clone the approved test repository.
        workspace, repository_path = clone_repository(
            request.owner,
            request.repo,
        )

        # Step 5: Create a local migration branch.
        branch_name = create_migration_branch(
            str(repository_path)
        )

        # Step 6: Apply all validated changes.
        apply_batch(
            str(repository_path),
            request.changes,
        )

        # Step 7: Identify modified files.
        changed_files = get_changed_files(
            str(repository_path)
        )

        # Step 8: Create and verify a real local Git commit.
        commit_result = create_local_migration_commit(
            repository_path=str(repository_path),
            changed_files=changed_files,
            commit_message=request.commit_message,
        )

        # Step 9: Prepare draft PR metadata.
        # This does not create a PR on GitHub.
        pull_request = build_pull_request_payload(
            branch_name=branch_name,
            changed_files=commit_result["committed_files"],
            summary=request.summary,
            base_branch=request.base_branch,
        )

        # Step 10: Return the local commit result.
        return LocalCommitResponse(
            repository=repository_name,
            branch_name=branch_name,
            commit_hash=commit_result["commit_hash"],
            short_commit_hash=commit_result["short_commit_hash"],
            commit_message=commit_result["commit_message"],
            committed_files=commit_result["committed_files"],
            total_committed_files=commit_result[
                "total_committed_files"
            ],
            pull_request=pull_request,
            remote_writes_enabled=False,
            status="committed_locally",
        )

    finally:
        # Step 11: Delete the temporary clone and its commit.
        if workspace is not None:
            cleanup_workspace(workspace)


# ============================================================
# API Guardian - End-to-End Publishing Workflow
# File: backend/services/migration_service.py
#
# Purpose:
#   Clone, patch, commit, publish, and open a draft PR.

# ============================================================


async def execute_github_migration(
    request: MigrationPlanRequest,
    *,
    authorized: bool = False,
) -> dict:
    """
    Execute the complete GitHub migration workflow.

    Refuses to run unless publishing is authorized.
    """

    # Reject unauthorized requests before cloning.
    if not authorized:
        raise PublishingError(
            "Remote publishing has not been authorized."
        )

    repository_name = f"{request.owner}/{request.repo}"

    validate_publish_target(repository_name)

    if os.getenv("API_GUARDIAN_ENABLE_PUBLISH") != "true":
        raise PublishingError(
            "Remote publishing is disabled."
        )

    # Validate PR metadata before performing Git operations.
    build_pull_request_payload(
        branch_name="api-guardian/migration-validation",
        changed_files=[
            change.file_path for change in request.changes
        ],
        summary=request.summary,
        base_branch=request.base_branch,
    )

    workspace = None

    try:
        # Clone the repository.
        workspace, repository_path = clone_repository(
            request.owner,
            request.repo,
        )

        # Create migration branch.
        branch_name = create_migration_branch(
            str(repository_path)
        )

        # Apply proposed code changes.
        apply_batch(
            str(repository_path),
            request.changes,
        )

        # Identify changed files.
        changed_files = get_changed_files(
            str(repository_path)
        )

        # Create a real local commit.
        commit_result = create_local_migration_commit(
            repository_path=str(repository_path),
            changed_files=changed_files,
            commit_message=request.commit_message,
        )

        # Prepare draft PR metadata.
        pr_payload = build_pull_request_payload(
            branch_name=branch_name,
            changed_files=commit_result["committed_files"],
            summary=request.summary,
            base_branch=request.base_branch,
        )

        # Publish the branch to GitHub.
        branch_result = publish_migration_branch(
            repository_path=str(repository_path),
            repository_name=repository_name,
            branch_name=branch_name,
            authorized=authorized,
        )

        # Create the draft pull request.
        pr_result = await create_draft_pull_request(
            repository_name=repository_name,
            payload=pr_payload,
            authorized=authorized,
        )

        return {
            "repository": repository_name,
            "branch_name": branch_name,
            "commit_hash": commit_result["commit_hash"],
            "branch_status": branch_result["status"],
            "pull_request_number": pr_result[
                "pull_request_number"
            ],
            "pull_request_url": pr_result[
                "pull_request_url"
            ],
            "status": "published",
        }

    finally:
        if workspace is not None:
            cleanup_workspace(workspace)
