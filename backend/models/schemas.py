# ============================================================
# API Guardian - Data Models
# File: backend/models/schemas.py
#
# Purpose:
#   Define request and response models for API migrations.
#
# Python: 3.10+
# ============================================================

from typing import Any

from pydantic import BaseModel, Field


class MigrationRequest(BaseModel):
    owner: str | None = None
    repo: str | None = None
    repo_url: str | None = None
    changelog: str = ""
    branch: str | None = None
    all_branches: bool = True


class FileChange(BaseModel):
    file_path: str
    original_code: str
    updated_code: str
    explanation: str
    branch: str | None = None


class APIUsage(BaseModel):
    file_path: str
    branch: str
    provider: str
    evidence: str
    dependency_version: str | None = None


class APIFinding(BaseModel):
    fingerprint: str = ""
    file_path: str
    branch: str
    severity: str
    title: str
    evidence: str
    explanation: str
    recommendation: str
    proposed_code: str | None = None
    lifecycle_status: str = "new"
    verification_status: str = "not_run"
    verification_message: str | None = None
    first_seen_at: str | None = None
    last_seen_at: str | None = None
    resolved_in_commit_sha: str | None = None
    resolved_at: str | None = None


class ScannedRevision(BaseModel):
    branch: str
    commit_sha: str


class MigrationResponse(BaseModel):
    repository: str
    breaking_change: bool
    affected_files: list[FileChange]
    summary: str
    status: str
    branches_scanned: list[str] = Field(default_factory=list)
    scanned_revisions: list[ScannedRevision] = Field(default_factory=list)
    api_detected: bool = False
    api_usages: list[APIUsage] = Field(default_factory=list)
    findings: list[APIFinding] = Field(default_factory=list)
    resolved_findings: list[APIFinding] = Field(default_factory=list)
    scan_id: str | None = None
    history_reconciled: bool = False
    history_message: str | None = None


class FixProposalRequest(MigrationRequest):
    """Ask the repair agent to address one specific audit finding."""

    file_path: str = Field(min_length=1)
    finding_title: str = Field(min_length=1)
    problem: str = Field(min_length=1)
    recommendation: str = Field(min_length=1)
    expected_commit_sha: str | None = None


class FixProposalResponse(BaseModel):
    """A validated code proposal and its local diff."""

    change: FileChange
    changes: list[FileChange] = Field(default_factory=list)
    diff: str
    status: str
    verification_status: str = "not_run"
    verification_message: str | None = None
    branch: str | None = None
    base_commit_sha: str | None = None


class PatchPreviewRequest(BaseModel):
    owner: str
    repo: str
    changes: list[FileChange] = Field(min_length=1)


class PatchPreviewResult(BaseModel):
    file_path: str
    valid: bool
    diff: str | None = None
    error: str | None = None


class PatchPreviewResponse(BaseModel):
    repository: str
    total_changes: int
    valid_changes: int
    results: list[PatchPreviewResult]
    status: str


# ============================================================
# API Guardian - Batch Application Response Models
#
# Purpose:
#   Define the response returned after applying a batch
#   of patches to a temporary repository workspace.
#
# Python: 3.10+
# ============================================================


class AppliedFileResult(BaseModel):
    """Information about one successfully patched file."""

    file_path: str
    diff: str
    status: str


class BatchApplyResponse(BaseModel):
    """Summary of a batch patch application."""

    repository: str
    total_changes: int
    applied_changes: int
    results: list[AppliedFileResult]
    status: str


# ============================================================
# API Guardian - Migration Preparation Response Model
#
# Purpose:
#   Describe the Git branch and code changes prepared
#   inside a temporary repository workspace.
#
# Python: 3.10+
# ============================================================


class MigrationPrepareResponse(BaseModel):
    """
    Response returned after preparing a local migration.

    The branch exists only in the temporary workspace.
    """

    repository: str
    branch_name: str
    changed_files: list[str]
    total_changed_files: int
    diff: str
    status: str


# ============================================================
# API Guardian - Pull Request Preparation Schemas
# File: backend/models/schemas.py
#
# Purpose:
#   Validate requests and responses for the combined
#   migration and pull request preparation workflow.
#
# Python: 3.10+
# Team: Member 2 - Backend & GitHub Integration
# ============================================================


class PreparePullRequestRequest(PatchPreviewRequest):
    """
    Extend the existing patch request with PR metadata.
    """

    summary: str = Field(min_length=1)
    base_branch: str = Field(default="main", min_length=1)


class PreparePullRequestResponse(BaseModel):
    """
    Describe the prepared migration and GitHub PR payload.

    No remote branch or pull request is created.
    """

    repository: str
    branch_name: str
    changed_files: list[str]
    total_changed_files: int
    diff: str
    pull_request: dict
    status: str


# ============================================================
# API Guardian - Complete Migration Plan Schemas
# File: backend/models/schemas.py
#
# Purpose:
#   Define the request and response models for a complete
#   migration plan, including commit and PR metadata.
#
# Python: 3.10+
# Team: Member 2 - Backend & GitHub Integration
# ============================================================


class MigrationPlanRequest(PreparePullRequestRequest):
    """
    Extend the PR preparation request with commit metadata.
    """

    commit_message: str = Field(
        default="fix: migrate deprecated API usage",
        min_length=1,
    )
    expected_base_commit_sha: str | None = None


class MigrationPlanResponse(BaseModel):
    """
    Complete migration plan returned by the backend.

    No GitHub modifications are performed.
    """

    repository: str
    branch_name: str
    changed_files: list[str]
    total_changed_files: int
    diff: str
    commit_plan: dict
    pull_request: dict
    status: str
    base_commit_sha: str | None = None

# ============================================================
# API Guardian - Publishing Dry-Run Response Schema
# File: backend/models/schemas.py
#
# Purpose:
#   Describe the migration plan and proposed GitHub
#   publishing operations without executing them.
# ============================================================


class PublishDryRunResponse(BaseModel):
    """
    Response for the GitHub publishing dry-run endpoint.
    """

    repository: str
    branch_name: str
    migration_status: str
    changed_files: list[str]
    diff: str
    commit_plan: dict[str, Any]
    pull_request: dict[str, Any]
    operations: list[dict[str, Any]]
    remote_writes_enabled: bool
    status: str


class PublishStatusResponse(BaseModel):
    """GitHub write readiness without exposing credentials."""

    repository: str | None = None
    repository_approved: bool
    token_configured: bool
    remote_writes_enabled: bool
    publish_ready: bool
    readiness_issues: list[str] = Field(default_factory=list)


class PublishReviewResponse(BaseModel):
    """An immutable, expiring code diff prepared for user review."""

    review_id: str
    repository: str
    branch_name: str
    base_branch: str
    base_commit_sha: str
    changed_files: list[str]
    diff: str
    pull_request: dict[str, Any]
    publish_ready: bool
    readiness_issues: list[str] = Field(default_factory=list)
    expires_in_seconds: int
    status: str


class PublishApprovalRequest(BaseModel):
    """Explicit approval for one prepared review."""

    review_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    approved: bool


class GitHubPublishResponse(BaseModel):
    """Result of publishing a reviewed branch and draft pull request."""

    repository: str
    branch_name: str
    commit_hash: str
    branch_status: str
    pull_request_number: int
    pull_request_url: str
    status: str

# ============================================================
# API Guardian - Local Commit Execution Response
# File: backend/models/schemas.py
#
# Purpose:
#   Define the response returned when API Guardian
#   creates a Git commit in a temporary repository.
# ============================================================


class LocalCommitResponse(BaseModel):
    """
    Result of preparing and committing an API migration locally.
    """

    repository: str
    branch_name: str
    commit_hash: str
    short_commit_hash: str
    commit_message: str
    committed_files: list[str]
    total_committed_files: int
    pull_request: dict
    remote_writes_enabled: bool
    status: str
