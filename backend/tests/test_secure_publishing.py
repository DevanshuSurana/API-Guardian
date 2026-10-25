# ============================================================
# API Guardian - Secure Publishing Tests
# File: backend/test_secure_publishing.py
#
# Purpose:
#   Confirm that remote publishing is blocked when
#   authorization or publishing configuration is missing.
# ============================================================

import os
import subprocess
from unittest.mock import patch

from git import Repo

from services import github_publish_executor as publisher
from services.github_publish_executor import (
    PublishingError,
    publish_migration_branch,
)


def test_unauthorized_push():
    """
    Verify that an unauthorized push is rejected
    before accessing the local Git repository.
    """

    try:
        publish_migration_branch(
            repository_path="/nonexistent/repository",
            repository_name="sneha0832/api-guardian-test-repo",
            branch_name="api-guardian/migration-test123",
            authorized=False,
        )
    except PublishingError:
        print("Unauthorized push correctly blocked.")
        return

    raise AssertionError("Unauthorized push was not blocked.")


def test_disabled_publishing():
    """
    Verify that publishing remains disabled even
    when the internal authorization flag is True.
    """

    with patch.dict(
        os.environ,
        {"API_GUARDIAN_ENABLE_PUBLISH": "false"},
    ):
        try:
            publish_migration_branch(
                repository_path="/nonexistent/repository",
                repository_name="sneha0832/api-guardian-test-repo",
                branch_name="api-guardian/migration-test123",
                authorized=True,
            )
        except PublishingError:
            print("Disabled publishing correctly blocked.")
            return

    raise AssertionError("Disabled publishing was not blocked.")


def test_unapproved_repository():
    """
    Verify that an unauthorized destination
    is rejected before any Git operation.
    """

    try:
        publish_migration_branch(
            repository_path="/nonexistent/repository",
            repository_name="DevanshuSurana/API-Guardian",
            branch_name="api-guardian/migration-test123",
            authorized=True,
        )
    except ValueError:
        print("Unapproved repository correctly blocked.")
        return

    raise AssertionError("Unapproved repository was not blocked.")


def _clean_migration_repository(tmp_path):
    repository_path = tmp_path / "repo"
    repository_path.mkdir()
    repository = Repo.init(repository_path, initial_branch="main")
    with repository.config_writer() as config:
        config.set_value("user", "name", "API Guardian Tests")
        config.set_value("user", "email", "tests@example.com")
    (repository_path / "README.md").write_text("clean\n", encoding="utf-8")
    repository.index.add(["README.md"])
    repository.index.commit("initial commit")
    branch_name = "api-guardian/migration-test123"
    repository.git.checkout("-b", branch_name)
    repository.create_remote(
        "origin",
        "https://github.com/sneha0832/api-guardian-test-repo.git",
    )
    return repository_path, branch_name


def test_authorized_push_uses_environment_credentials_without_leaking_token(
    tmp_path, monkeypatch
):
    repository_path, branch_name = _clean_migration_repository(tmp_path)
    monkeypatch.setenv("API_GUARDIAN_ENABLE_PUBLISH", "true")
    monkeypatch.setattr(publisher, "get_github_token", lambda: "secret-token")
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(publisher.subprocess, "run", fake_run)

    result = publish_migration_branch(
        repository_path=str(repository_path),
        repository_name="sneha0832/api-guardian-test-repo",
        branch_name=branch_name,
        authorized=True,
    )

    assert result["status"] == "branch_published"
    assert len(calls) == 1
    command, options = calls[0]
    assert "secret-token" not in " ".join(command)
    assert "secret-token" not in options["env"]["GIT_CONFIG_VALUE_0"]
    assert "AUTHORIZATION: basic" in options["env"]["GIT_CONFIG_VALUE_0"]


def test_push_process_errors_are_reported_as_publishing_errors(tmp_path, monkeypatch):
    repository_path, branch_name = _clean_migration_repository(tmp_path)
    monkeypatch.setenv("API_GUARDIAN_ENABLE_PUBLISH", "true")
    monkeypatch.setattr(publisher, "get_github_token", lambda: "secret-token")

    for error in (
        subprocess.CalledProcessError(1, ["git", "push"]),
        subprocess.TimeoutExpired(["git", "push"], 60),
    ):

        def failed_run(*_args, _error=error, **_kwargs):
            raise _error

        monkeypatch.setattr(publisher.subprocess, "run", failed_run)
        with patch.dict(os.environ, {"API_GUARDIAN_ENABLE_PUBLISH": "true"}):
            try:
                publish_migration_branch(
                    repository_path=str(repository_path),
                    repository_name="sneha0832/api-guardian-test-repo",
                    branch_name=branch_name,
                    authorized=True,
                )
            except PublishingError:
                continue
            raise AssertionError("Git process errors must be wrapped safely.")


if __name__ == "__main__":
    test_unauthorized_push()
    test_disabled_publishing()
    test_unapproved_repository()

    print("\nAll secure publishing tests passed!")
