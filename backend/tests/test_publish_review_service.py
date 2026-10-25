import asyncio
import time

import pytest
from git import Repo

from models.schemas import (
    MigrationPlanRequest,
    MigrationPlanResponse,
    PublishApprovalRequest,
)
from services import migration_service
from services import publish_review_service as reviews
from services.github_publish_executor import PublishingError
from services.repository_service import StaleRepositoryRevisionError


def _request():
    from models.schemas import FileChange

    return MigrationPlanRequest(
        owner="example",
        repo="client",
        changes=[
            FileChange(
                file_path="client.py",
                original_code="client.old_call()\n",
                updated_code="client.new_call()\n",
                explanation="Migrate the deprecated API call.",
            )
        ],
        summary="Migrate deprecated API call.",
        base_branch="main",
        commit_message="fix: migrate API call",
    )


def test_prepare_review_caches_exact_diff_without_writes(monkeypatch):
    request = _request()
    migration = MigrationPlanResponse(
        repository="example/client",
        branch_name="api-guardian/migration-0123456789ab",
        changed_files=["client.py"],
        total_changed_files=1,
        diff="-client.old_call()\n+client.new_call()\n",
        commit_plan={"commit_message": "fix: migrate API call"},
        pull_request={"head": "api-guardian/migration-0123456789ab", "draft": True},
        status="migration_plan_prepared",
        base_commit_sha="a" * 40,
    )
    monkeypatch.setattr(reviews, "create_migration_plan", lambda *_args, **_kwargs: migration)
    monkeypatch.setattr(
        reviews,
        "publishing_readiness",
        lambda repository: {
            "publish_ready": False,
            "readiness_issues": ["Publishing is disabled."],
        },
    )
    reviews._pending_reviews.clear()

    result = reviews.prepare_publish_review(request)

    assert result.status == "review_prepared"
    assert result.diff == migration.diff
    assert result.base_commit_sha == "a" * 40
    assert not result.publish_ready
    assert result.review_id in reviews._pending_reviews


def test_migration_plan_rejects_a_base_changed_since_the_scan(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    repository_path = workspace / "repository"
    repository_path.mkdir(parents=True)
    repository = Repo.init(repository_path, initial_branch="main")
    repository.config_writer().set_value("user", "name", "API Guardian Test").release()
    repository.config_writer().set_value("user", "email", "test@example.com").release()
    (repository_path / "client.py").write_text("client.old_call()\n", encoding="utf-8")
    repository.index.add(["client.py"])
    repository.index.commit("initial commit")
    monkeypatch.setattr(
        migration_service,
        "clone_repository",
        lambda *_args, **_kwargs: (workspace, repository_path),
    )
    request = _request().model_copy(update={"expected_base_commit_sha": "f" * 40})

    with pytest.raises(StaleRepositoryRevisionError, match="changed after this scan"):
        migration_service.create_migration_plan(request)

    assert not workspace.exists()


def test_unchecked_approval_is_rejected():
    with pytest.raises(PublishingError, match="explicit approval"):
        asyncio.run(
            reviews.approve_and_publish(
                PublishApprovalRequest(review_id="a" * 32, approved=False)
            )
        )


def test_approval_consumes_review_once_and_publishes(monkeypatch):
    review_id = "b" * 32
    pending = reviews.PendingPublishReview(
        request=_request(),
        repository="example/client",
        branch_name="api-guardian/migration-bbbbbbbbbbbb",
        base_commit_sha="c" * 40,
        diff="verified diff",
    )
    reviews._pending_reviews[review_id] = (time.time() + 60, pending)
    monkeypatch.setattr(
        reviews,
        "publishing_readiness",
        lambda _repository: {"publish_ready": True, "readiness_issues": []},
    )
    calls = {}

    async def fake_publish(request, **kwargs):
        calls["request"] = request
        calls.update(kwargs)
        return {
            "repository": "example/client",
            "branch_name": pending.branch_name,
            "commit_hash": "d" * 40,
            "branch_status": "branch_published",
            "pull_request_number": 7,
            "pull_request_url": "https://github.com/example/client/pull/7",
            "status": "published",
        }

    monkeypatch.setattr(reviews, "execute_github_migration", fake_publish)
    result = asyncio.run(
        reviews.approve_and_publish(
            PublishApprovalRequest(review_id=review_id, approved=True)
        )
    )

    assert result.pull_request_number == 7
    assert calls["authorized"] is True
    assert calls["expected_base_commit_sha"] == "c" * 40
    assert calls["expected_diff"] == "verified diff"
    assert calls["branch_name"] == pending.branch_name
    assert review_id not in reviews._pending_reviews


def test_expired_review_cannot_be_approved():
    review_id = "e" * 32
    reviews._pending_reviews[review_id] = (
        time.time() - 1,
        reviews.PendingPublishReview(
            request=_request(),
            repository="example/client",
            branch_name="api-guardian/migration-eeeeeeeeeeee",
            base_commit_sha="f" * 40,
            diff="expired",
        ),
    )

    with pytest.raises(PublishingError, match="expired"):
        asyncio.run(
            reviews.approve_and_publish(
                PublishApprovalRequest(review_id=review_id, approved=True)
            )
        )


def test_publish_readiness_requires_explicit_allowlist_token_and_switch(monkeypatch):
    from services.github_publish_service import publishing_readiness

    monkeypatch.setenv("API_GUARDIAN_ALLOWED_REPOSITORIES", "example/client")
    monkeypatch.setenv("GITHUB_TOKEN", "token-value")
    monkeypatch.setenv("API_GUARDIAN_ENABLE_PUBLISH", "true")

    ready = publishing_readiness("EXAMPLE/CLIENT")
    assert ready["publish_ready"] is True
    assert ready["token_configured"] is True
    assert ready["readiness_issues"] == []

    not_allowed = publishing_readiness("example/other")
    assert not_allowed["publish_ready"] is False
    assert not_allowed["repository_approved"] is False
    assert "token-value" not in str(not_allowed)
