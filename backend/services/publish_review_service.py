"""Prepare immutable, expiring migration reviews before GitHub writes."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from uuid import uuid4

from models.schemas import (
    GitHubPublishResponse,
    MigrationPlanRequest,
    PublishApprovalRequest,
    PublishReviewResponse,
    PublishStatusResponse,
)
from services.github_publish_executor import PublishingError
from services.github_publish_service import publishing_readiness
from services.migration_service import create_migration_plan, execute_github_migration

REVIEW_TTL_SECONDS = 15 * 60
_review_lock = threading.Lock()


@dataclass(frozen=True)
class PendingPublishReview:
    request: MigrationPlanRequest
    repository: str
    branch_name: str
    base_commit_sha: str
    diff: str


_pending_reviews: dict[str, tuple[float, PendingPublishReview]] = {}


def _remove_expired_reviews(now: float | None = None) -> None:
    current_time = now if now is not None else time.time()
    expired = [
        review_id
        for review_id, (expires_at, _) in _pending_reviews.items()
        if expires_at <= current_time
    ]
    for review_id in expired:
        _pending_reviews.pop(review_id, None)


def get_publish_status(repository: str | None = None) -> PublishStatusResponse:
    """Return publishing readiness without exposing any credential value."""
    return PublishStatusResponse(**publishing_readiness(repository))


def prepare_publish_review(request: MigrationPlanRequest) -> PublishReviewResponse:
    """Prepare a branch and exact diff locally, then cache the review briefly."""
    review_id = uuid4().hex
    branch_name = f"api-guardian/migration-{review_id[:12]}"
    migration = create_migration_plan(request, branch_name=branch_name)
    repository = migration.repository
    readiness = publishing_readiness(repository)

    if not migration.base_commit_sha:
        raise RuntimeError("Could not record the repository commit used for review.")

    pending = PendingPublishReview(
        request=request.model_copy(deep=True),
        repository=repository,
        branch_name=migration.branch_name,
        base_commit_sha=migration.base_commit_sha,
        diff=migration.diff,
    )
    with _review_lock:
        _remove_expired_reviews()
        _pending_reviews[review_id] = (time.time() + REVIEW_TTL_SECONDS, pending)

    return PublishReviewResponse(
        review_id=review_id,
        repository=repository,
        branch_name=migration.branch_name,
        base_branch=request.base_branch,
        base_commit_sha=migration.base_commit_sha,
        changed_files=migration.changed_files,
        diff=migration.diff,
        pull_request=migration.pull_request,
        publish_ready=readiness["publish_ready"],
        readiness_issues=readiness["readiness_issues"],
        expires_in_seconds=REVIEW_TTL_SECONDS,
        status="review_prepared",
    )


def _get_pending_review(review_id: str) -> PendingPublishReview | None:
    with _review_lock:
        _remove_expired_reviews()
        entry = _pending_reviews.get(review_id)
        return entry[1] if entry else None


def _consume_pending_review(review_id: str) -> PendingPublishReview | None:
    with _review_lock:
        _remove_expired_reviews()
        entry = _pending_reviews.pop(review_id, None)
        return entry[1] if entry else None


async def approve_and_publish(
    approval: PublishApprovalRequest,
) -> GitHubPublishResponse:
    """Consume one reviewed plan and publish it only after an explicit approval."""
    if not approval.approved:
        raise PublishingError("Publishing requires explicit approval of the reviewed diff.")

    pending = _get_pending_review(approval.review_id)
    if pending is None:
        raise PublishingError(
            "This review expired or was already used. Prepare the diff again."
        )

    readiness = publishing_readiness(pending.repository)
    if not readiness["publish_ready"]:
        raise PublishingError("Publishing is not configured: " + " ".join(readiness["readiness_issues"]))

    # Consume before making network writes so the review cannot be replayed.
    pending = _consume_pending_review(approval.review_id)
    if pending is None:
        raise PublishingError("This review was already approved or expired.")

    result = await execute_github_migration(
        pending.request,
        authorized=True,
        expected_base_commit_sha=pending.base_commit_sha,
        expected_diff=pending.diff,
        branch_name=pending.branch_name,
    )
    return GitHubPublishResponse(**result)
