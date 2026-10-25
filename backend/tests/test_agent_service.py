import asyncio

import pytest
from models.schemas import FileChange
from services import agent_service


def _mock_repo(monkeypatch, workspace, repository, branches):
    monkeypatch.setattr(
        agent_service,
        "clone_repository",
        lambda owner, repo, **kwargs: (workspace, repository),
    )
    monkeypatch.setattr(agent_service, "repository_branches", lambda path: branches)
    monkeypatch.setattr(agent_service, "checkout_repository_branch", lambda path, branch: None)
    monkeypatch.setattr(agent_service, "checked_out_commit_sha", lambda path: "a" * 40)
    monkeypatch.setattr(
        agent_service,
        "SCAN_HISTORY_DATABASE_PATH",
        workspace / "scan-history.db",
    )


def test_proposed_fix_is_blocked_when_follow_up_audit_still_finds_issue(monkeypatch):
    monkeypatch.setattr(
        agent_service,
        "audit_source_for_api_issues",
        lambda *_args: {"findings": [{"title": "Removed API argument"}]},
    )

    verification = agent_service._verify_proposed_fixes(
        "client.py",
        "httpx dependency",
        [{
            "title": "Removed API argument",
            "proposed_code": "client.request(new_arg=True)\n",
        }],
    )

    assert verification["Removed API argument"][0] == "still_detected"


def test_analyze_migration_scans_all_files_without_count_or_size_caps(
    tmp_path, monkeypatch
):
    workspace = tmp_path / "workspace"
    repository = workspace / "repository"
    repository.mkdir(parents=True)
    relative_paths = []
    for index in range(24):
        relative_path = f"src/client_{index:02}.py"
        path = repository / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("client.old_call()\n" if index == 23 else "pass\n")
        relative_paths.append(relative_path)
    large_path = repository / "src" / "large.py"
    large_path.write_text("# source\n" + "x = 1\n" * 30_000)
    relative_paths.append("src/large.py")

    _mock_repo(monkeypatch, workspace, repository, ["main"])
    monkeypatch.setattr(agent_service, "list_source_files", lambda path: relative_paths)
    analyzed = []
    statically_checked = []
    detect_api_usages = agent_service.detect_api_usages

    def track_static_check(source_code, file_path, branch, dependency_versions):
        statically_checked.append(file_path)
        return detect_api_usages(source_code, file_path, branch, dependency_versions)

    monkeypatch.setattr(agent_service, "detect_api_usages", track_static_check)

    def analyze_file(**kwargs):
        analyzed.append(kwargs["file_path"])
        return True, None

    monkeypatch.setattr(agent_service, "analyze_source_with_ai", analyze_file)
    result = asyncio.run(
        agent_service.analyze_migration(
            agent_service.MigrationRequest(
                owner="example",
                repo="client",
                changelog="old_call was removed.",
            )
        )
    )

    assert statically_checked == relative_paths
    assert analyzed == ["src/client_23.py"]
    assert result.status == "analysis_complete"
    assert result.branches_scanned == ["main"]
    assert result.scanned_revisions[0].commit_sha == "a" * 40
    assert "Analyzed 25 source files" in result.summary
    assert "AI reviewed 1 likely candidates" in result.summary
    assert "Skipped" not in result.summary
    assert not workspace.exists()


def test_analyze_migration_scans_every_file_on_every_branch(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    repository = workspace / "repository"
    repository.mkdir(parents=True)
    (repository / "client.py").write_text("client.old_call()\n")
    _mock_repo(monkeypatch, workspace, repository, ["main", "release/2.x"])
    monkeypatch.setattr(agent_service, "list_source_files", lambda path: ["client.py"])
    analyzed = []

    def analyze_file(**kwargs):
        analyzed.append(kwargs["file_path"])
        return True, FileChange(
            file_path=kwargs["file_path"],
            original_code=kwargs["source_code"],
            updated_code="client.new_call()\n",
            explanation="Migration",
        )

    monkeypatch.setattr(agent_service, "analyze_source_with_ai", analyze_file)
    result = asyncio.run(
        agent_service.analyze_migration(
            agent_service.MigrationRequest(
                owner="example",
                repo="client",
                changelog="old_call was removed.",
                all_branches=True,
            )
        )
    )

    assert analyzed == ["client.py", "client.py"]
    assert result.branches_scanned == ["main", "release/2.x"]
    assert [change.branch for change in result.affected_files] == ["main", "release/2.x"]
    assert "Scanned 2 branches" in result.summary
    assert not workspace.exists()


def test_analyze_migration_accepts_one_named_branch(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    repository = workspace / "repository"
    repository.mkdir(parents=True)
    (repository / "client.py").write_text("pass\n")
    clone_args = {}
    monkeypatch.setattr(
        agent_service,
        "clone_repository",
        lambda owner, repo, **kwargs: (clone_args.update(kwargs) or (workspace, repository)),
    )
    monkeypatch.setattr(agent_service, "repository_branches", lambda path: ["main"])
    monkeypatch.setattr(agent_service, "checked_out_commit_sha", lambda path: "b" * 40)
    monkeypatch.setattr(
        agent_service,
        "SCAN_HISTORY_DATABASE_PATH",
        tmp_path / "scan-history.db",
    )
    checked_out = []
    monkeypatch.setattr(
        agent_service,
        "checkout_repository_branch",
        lambda path, branch: checked_out.append(branch),
    )
    monkeypatch.setattr(agent_service, "list_source_files", lambda path: ["client.py"])
    monkeypatch.setattr(agent_service, "analyze_source_with_ai", lambda **kwargs: (False, None))

    result = asyncio.run(
        agent_service.analyze_migration(
            agent_service.MigrationRequest(
                owner="example",
                repo="client",
                changelog="No breaking change.",
                branch="feature/custom",
                all_branches=False,
            )
        )
    )

    assert clone_args == {"all_branches": False, "branch": "feature/custom"}
    assert checked_out == ["feature/custom"]
    assert result.branches_scanned == ["feature/custom"]
    assert not workspace.exists()


def test_automatic_audit_finds_api_calls_and_proposes_verified_fix(
    tmp_path, monkeypatch
):
    workspace = tmp_path / "workspace"
    repository = workspace / "repository"
    repository.mkdir(parents=True)
    source = (
        "notion_client = object()\n"
        "database_id = 'database-id'\n"
        "data_source_id = 'source-id'\n"
        "result = notion_client.databases.query(database_id=database_id)\n"
    )
    (repository / "tasks.py").write_text(source)
    _mock_repo(monkeypatch, workspace, repository, ["main"])
    monkeypatch.setattr(agent_service, "list_source_files", lambda path: ["tasks.py"])
    monkeypatch.setattr(
        agent_service,
        "audit_source_for_api_issues",
        lambda source_code, file_path, dependency_context: {
            "api_detected": True,
            "api_usages": [
                "notion_client.databases.query(database_id=database_id)"
            ],
            "findings": [{
                "title": "Notion database queries need a data-source migration",
                "severity": "high",
                "evidence": (
                    "notion_client.databases.query(database_id=database_id)"
                ),
                "explanation": "The new API queries a data source.",
                "recommendation": "Use a data source ID and query method.",
                "proposed_code": (
                    "notion_client = object()\n"
                    "database_id = 'database-id'\n"
                    "data_source_id = 'source-id'\n"
                    "result = notion_client.data_sources.query("
                    "data_source_id=data_source_id)\n"
                ),
            }],
        },
    )

    result = asyncio.run(
        agent_service.analyze_migration(
            agent_service.MigrationRequest(
                repo_url="https://github.com/example/notion-app.git",
                all_branches=False,
                branch="main",
            )
        )
    )

    assert result.repository == "example/notion-app"
    assert result.api_detected is True
    assert result.api_usages[0].provider == "Notion"
    assert result.findings[0].severity == "medium"
    assert "notion_client.data_sources" in result.affected_files[0].updated_code
    assert result.breaking_change is True
    assert not workspace.exists()


def test_automatic_audit_drops_generic_advice_and_rejects_unsafe_fix(
    tmp_path, monkeypatch
):
    workspace = tmp_path / "workspace"
    repository = workspace / "repository"
    repository.mkdir(parents=True)
    source = '''import requests

def fetch_post(post_id=1):
    response = requests.get(f"https://example.test/posts/{post_id}")
    response.raise_for_status()
    return response.json()
'''
    (repository / "client.py").write_text(source, encoding="utf-8")
    _mock_repo(monkeypatch, workspace, repository, ["main"])
    monkeypatch.setattr(agent_service, "list_source_files", lambda _path: ["client.py"])
    generic_advice = {
        "title": "HTTP request to Example API",
        "severity": "high",
        "evidence": "requests.get(f\"https://example.test/posts/{post_id}\")",
        "explanation": "The code uses requests.get to make an HTTP request.",
        "recommendation": "Consider using a more robust HTTP client like httpx.",
        "proposed_code": source,
    }
    unsafe_compatibility_fix = {
        "title": "Removed HTTP parameter",
        "severity": "high",
        "evidence": "requests.get(f\"https://example.test/posts/{post_id}\")",
        "explanation": "The API removed this parameter and the old call will fail.",
        "recommendation": "Use the supported request parameter.",
        "proposed_code": '''import requests

def fetch_post(post_id=1):
    response.raise_for_status()
    return response.json()
''',
    }
    monkeypatch.setattr(
        agent_service,
        "audit_source_for_api_issues",
        lambda *_args: {
            "api_detected": True,
            "api_usages": [generic_advice["evidence"]],
            "findings": [generic_advice, unsafe_compatibility_fix],
        },
    )

    result = asyncio.run(
        agent_service.analyze_migration(
            agent_service.MigrationRequest(
                owner="example",
                repo="client",
                all_branches=False,
                branch="main",
            )
        )
    )

    assert len(result.api_usages) == 1
    assert len(result.findings) == 1
    assert result.findings[0].title == "Removed HTTP parameter"
    assert result.findings[0].proposed_code is None
    assert result.affected_files == []
    assert result.breaking_change is True
    assert not workspace.exists()


def test_automatic_audit_reports_verified_figma_nodes_parameter_fix(
    tmp_path, monkeypatch
):
    workspace = tmp_path / "workspace"
    repository = workspace / "repository"
    repository.mkdir(parents=True)
    source = '''import httpx
import re

class FigmaError(Exception):
    pass

def extract_file_key(key):
    return key

BASE_URL = "https://api.figma.com/v1"

class FigmaClient:
    async def get_file(self, key):
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"https://api.figma.com/v1/file/{extract_file_key(key)}",
                headers={"X-Figma-Token": self.token},
            )
            response.raise_for_status()
            return response.json()

    async def get_nodes(self, key, node_ids):
        # REQUEST 2: Incorrect Figma API query parameter
        # BUG: node_ids should be ids
        if not node_ids or len(node_ids) > 10 or any(
            not re.fullmatch(r"[0-9]+:[0-9]+", node)
            for node in node_ids
        ):
            raise FigmaError("Provide 1-10 valid node IDs.", 400)
        return await self.request(
            f"/files/{extract_file_key(key)}/nodes",
            {"node_ids": ",".join(node_ids)},
        )
'''
    (repository / "figma_client.py").write_text(source, encoding="utf-8")
    _mock_repo(monkeypatch, workspace, repository, ["main"])
    monkeypatch.setattr(
        agent_service,
        "list_source_files",
        lambda _path: ["figma_client.py"],
    )
    monkeypatch.setattr(
        agent_service,
        "audit_source_for_api_issues",
        lambda *_args: {
            "api_detected": True,
            "api_usages": [],
            "findings": [{
                "title": "Incorrect Figma API query parameter",
                "severity": "high",
                "evidence": "# BUG: node_ids should be ids",
                "explanation": (
                    "The get_nodes method incorrectly passes node_ids as a string."
                ),
                "recommendation": (
                    "Format node_ids as a comma-separated string of valid IDs."
                ),
                "proposed_code": "",
            }],
        },
    )

    result = asyncio.run(
        agent_service.analyze_migration(
            agent_service.MigrationRequest(
                owner="example",
                repo="figma-client",
                all_branches=False,
                branch="main",
            )
        )
    )

    assert len(result.api_usages) == 3
    assert {usage.provider for usage in result.api_usages} == {
        "Figma REST API",
        "HTTPX",
    }
    assert len(result.findings) == 2
    assert {finding.severity for finding in result.findings} == {"high"}
    assert {finding.verification_status for finding in result.findings} == {"verified"}
    assert all(
        '"ids": ",".join(node_ids)' in finding.proposed_code
        for finding in result.findings
    )
    assert all(
        'f"https://api.figma.com/v1/files/{extract_file_key(key)}"'
        in finding.proposed_code
        for finding in result.findings
    )
    assert len(result.affected_files) == 1
    assert '"ids": ",".join(node_ids)' in result.affected_files[0].updated_code
    assert (
        'f"https://api.figma.com/v1/files/{extract_file_key(key)}"'
        in result.affected_files[0].updated_code
    )
    assert '"node_ids":' not in result.affected_files[0].updated_code
    assert result.breaking_change is True
    assert not workspace.exists()


def test_finding_fix_uses_deterministic_figma_rule_instead_of_model(
    tmp_path, monkeypatch
):
    workspace = tmp_path / "workspace"
    repository = workspace / "repository"
    repository.mkdir(parents=True)
    source = '''import re

class FigmaError(Exception):
    pass

def extract_file_key(key):
    return key

class FigmaClient:
    async def get_nodes(self, key, node_ids):
        if not node_ids or len(node_ids) > 10 or any(
            not re.fullmatch(r'[0-9]+:[0-9]+', node)
            for node in node_ids
        ):
            raise FigmaError('Provide 1-10 valid Figma node IDs (e.g. 1:2).', 400)
        return await self.request(
            f'/files/{extract_file_key(key)}/nodes',
            {'node_ids': ','.join(node_ids)}
        )
'''
    (repository / "figma_client.py").write_text(source, encoding="utf-8")
    monkeypatch.setattr(
        agent_service,
        "clone_repository",
        lambda owner, repo, **kwargs: (workspace, repository),
    )
    monkeypatch.setattr(agent_service, "checked_out_commit_sha", lambda _path: "a" * 40)
    monkeypatch.setattr(
        agent_service,
        "analyze_source_with_ai",
        lambda **_kwargs: pytest.fail("Known Figma repairs must not call the model"),
    )

    proposal = agent_service.generate_finding_fix(
        agent_service.FixProposalRequest(
            owner="example",
            repo="figma-client",
            branch="main",
            file_path="figma_client.py",
            finding_title="Incorrect Figma API query parameter",
            problem=(
                "The get_nodes method incorrectly passes node_ids as a string "
                "to the Figma API."
            ),
            recommendation=(
                "Rename the Figma query parameter to ids and keep the comma-"
                "separated node IDs."
            ),
            expected_commit_sha="a" * 40,
        )
    )

    assert proposal.status == "fix_proposed"
    assert proposal.verification_status == "verified"
    assert "{'ids': ','.join(node_ids)}" in proposal.change.updated_code
    assert "re.fullmatch" in proposal.change.updated_code
    assert "re.match" not in proposal.change.updated_code
    assert "{'node_ids':" not in proposal.change.updated_code
    assert not workspace.exists()


def test_changelog_audit_still_reports_detected_api_usage(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    repository = workspace / "repository"
    repository.mkdir(parents=True)
    source = "result = notion.databases.query(database_id=database_id)\n"
    (repository / "tasks.py").write_text(source)
    _mock_repo(monkeypatch, workspace, repository, ["main"])
    monkeypatch.setattr(agent_service, "list_source_files", lambda path: ["tasks.py"])
    monkeypatch.setattr(
        agent_service,
        "analyze_source_with_ai",
        lambda **kwargs: (True, None),
    )

    result = asyncio.run(
        agent_service.analyze_migration(
            agent_service.MigrationRequest(
                repo_url="https://github.com/example/notion-app",
                changelog="Database queries now require a data source ID.",
                all_branches=False,
                branch="main",
            )
        )
    )

    assert result.api_detected is True
    assert len(result.api_usages) == 1
    assert result.api_usages[0].provider == "Notion"
    assert result.breaking_change is True
    assert not workspace.exists()


def test_repository_url_must_be_github_and_match_explicit_identity():
    from services.agent_service import _repository_identity

    request = agent_service.MigrationRequest(
        repo_url="https://github.com/example/project.git"
    )
    assert _repository_identity(request) == ("example", "project")

    try:
        _repository_identity(
            agent_service.MigrationRequest(
                owner="other",
                repo="project",
                repo_url="https://github.com/example/project",
            )
        )
    except ValueError as error:
        assert "does not match" in str(error)
    else:
        raise AssertionError("A mismatched repository URL should be rejected")


def test_live_audit_includes_notions_legacy_query_migration_guidance(
    tmp_path, monkeypatch
):
    workspace = tmp_path / "workspace"
    repository = workspace / "repository"
    repository.mkdir(parents=True)
    source = (
        'NOTION_VERSION = "2022-06-28"\n'
        'url = f"https://api.notion.com/v1/databases/{database_id}/query"\n'
        'response = httpx.post(url, headers={"Notion-Version": NOTION_VERSION})\n'
    )
    (repository / "notion_client.py").write_text(source)
    _mock_repo(monkeypatch, workspace, repository, ["main"])
    monkeypatch.setattr(
        agent_service,
        "list_source_files",
        lambda path: ["notion_client.py"],
    )
    monkeypatch.setattr(
        agent_service,
        "audit_source_for_api_issues",
        lambda *args: {"api_detected": True, "api_usages": [], "findings": []},
    )

    result = asyncio.run(agent_service.analyze_migration(
        agent_service.MigrationRequest(
            repo_url="https://github.com/example/notion-app",
            all_branches=False,
            branch="main",
        )
    ))

    notion_finding = next(
        finding for finding in result.findings
        if "Notion database queries" in finding.title
    )
    assert "data_source_id" in notion_finding.recommendation
    assert notion_finding.proposed_code is None
    assert result.affected_files == []


def test_notion_audit_uses_version_from_config_and_ignores_docstring_text(
    tmp_path, monkeypatch
):
    workspace = tmp_path / "workspace"
    repository = workspace / "repository"
    app = repository / "app"
    app.mkdir(parents=True)
    (app / "config.py").write_text(
        "import os\nNOTION_VERSION = os.getenv('NOTION_VERSION', '2022-06-28')\n",
        encoding="utf-8",
    )
    (app / "notion_client.py").write_text(
        '''"""Notion-Version: 2022-06-28; old POST /v1/databases/{database_id}/query."""
async def query_database(self, database_id):
    return await self.request("POST", f"/databases/{database_id}/query")
''',
        encoding="utf-8",
    )
    _mock_repo(monkeypatch, workspace, repository, ["main"])
    monkeypatch.setattr(
        agent_service,
        "list_source_files",
        lambda _path: ["app/config.py", "app/notion_client.py"],
    )
    monkeypatch.setattr(
        agent_service,
        "audit_source_for_api_issues",
        lambda *_args: {"api_detected": True, "api_usages": [], "findings": []},
    )

    result = asyncio.run(agent_service.analyze_migration(
        agent_service.MigrationRequest(
            repo_url="https://github.com/example/notion-app",
            all_branches=False,
            branch="main",
        )
    ))

    assert len(result.findings) == 1
    assert result.findings[0].file_path == "app/notion_client.py"
    assert result.findings[0].title == "Notion database queries need a data-source migration"
    assert "NOTION_VERSION defaults" in result.findings[0].evidence
    assert {usage.provider for usage in result.api_usages} == {"Notion REST API"}
    assert not workspace.exists()


def test_notion_audit_does_not_report_old_text_in_docstring_after_migration(
    tmp_path, monkeypatch
):
    workspace = tmp_path / "workspace"
    repository = workspace / "repository"
    app = repository / "app"
    app.mkdir(parents=True)
    (app / "config.py").write_text(
        "import os\nNOTION_VERSION = os.getenv('NOTION_VERSION', '2025-09-03')\n",
        encoding="utf-8",
    )
    (app / "notion_client.py").write_text(
        '''"""Notion adapter uses new endpoints. Legacy: Notion-Version: 2022-06-28 and POST /v1/databases/{database_id}/query."""
async def query_database(self, data_source_id):
    return await self.request("POST", f"/data_sources/{data_source_id}/query")
''',
        encoding="utf-8",
    )
    _mock_repo(monkeypatch, workspace, repository, ["api-guardian/migration"])
    monkeypatch.setattr(
        agent_service,
        "list_source_files",
        lambda _path: ["app/config.py", "app/notion_client.py"],
    )
    monkeypatch.setattr(
        agent_service,
        "audit_source_for_api_issues",
        lambda *_args: {"api_detected": True, "api_usages": [], "findings": []},
    )

    result = asyncio.run(agent_service.analyze_migration(
        agent_service.MigrationRequest(
            repo_url="https://github.com/example/notion-app",
            all_branches=False,
            branch="api-guardian/migration",
        )
    ))

    assert result.findings == []
    assert not workspace.exists()


def test_generate_finding_fix_returns_validated_preview(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    repository = workspace / "repository"
    repository.mkdir(parents=True)
    source = "client.old_call()\n"
    (repository / "client.py").write_text(source, encoding="utf-8")
    monkeypatch.setattr(
        agent_service,
        "clone_repository",
        lambda owner, repo, **kwargs: (workspace, repository),
    )
    monkeypatch.setattr(agent_service, "checked_out_commit_sha", lambda path: "c" * 40)
    monkeypatch.setattr(
        agent_service,
        "audit_source_for_api_issues",
        lambda *_args: {"findings": []},
    )
    monkeypatch.setattr(
        agent_service,
        "analyze_source_with_ai",
        lambda **kwargs: (
            True,
            FileChange(
                file_path=kwargs["file_path"],
                original_code=kwargs["source_code"],
                updated_code="client.new_call()\n",
                explanation="Replace the removed client method.",
            ),
        ),
    )

    result = agent_service.generate_finding_fix(
        agent_service.FixProposalRequest(
            owner="example",
            repo="client",
            repo_url="https://github.com/example/client",
            branch="main",
            all_branches=False,
            file_path="client.py",
            finding_title="Removed method",
            problem="The client method was removed.",
            recommendation="Use the replacement method.",
            expected_commit_sha="c" * 40,
        )
    )

    assert result.status == "fix_proposed"
    assert result.verification_status == "recheck_passed"
    assert result.base_commit_sha == "c" * 40
    assert result.change.original_code == source
    assert result.change.updated_code == "client.new_call()\n"
    assert "-client.old_call()" in result.diff
    assert "+client.new_call()" in result.diff
    assert not workspace.exists()


def test_generate_finding_fix_rejects_a_stale_scan_revision(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    repository = workspace / "repository"
    repository.mkdir(parents=True)
    (repository / "client.py").write_text("client.old_call()\n", encoding="utf-8")
    monkeypatch.setattr(
        agent_service,
        "clone_repository",
        lambda owner, repo, **kwargs: (workspace, repository),
    )
    monkeypatch.setattr(agent_service, "checked_out_commit_sha", lambda path: "e" * 40)

    with pytest.raises(ValueError, match="changed after this scan"):
        agent_service.generate_finding_fix(
            agent_service.FixProposalRequest(
                owner="example",
                repo="client",
                branch="main",
                file_path="client.py",
                finding_title="Removed method",
                problem="The client method was removed.",
                recommendation="Use the replacement method.",
                expected_commit_sha="f" * 40,
            )
        )
    assert not workspace.exists()


def test_generate_finding_fix_refuses_unsupported_language():
    with pytest.raises(ValueError, match="Python fixes only"):
        agent_service.generate_finding_fix(
            agent_service.FixProposalRequest(
                owner="example",
                repo="client",
                file_path="client.ts",
                finding_title="Removed method",
                problem="The client method was removed.",
                recommendation="Use the replacement method.",
            )
        )


def test_generate_notion_data_source_fix_updates_client_config_and_env_example(
    tmp_path, monkeypatch
):
    workspace = tmp_path / "workspace"
    repository = workspace / "repository"
    app = repository / "app"
    app.mkdir(parents=True)
    client_source = '''import httpx
from fastapi import HTTPException
from app.config import NOTION_API_BASE, NOTION_VERSION, notion_settings


class NotionClient:
    def __init__(self, transport=None):
        token, self.database_id = notion_settings()
        self.headers = {
            'Authorization': f'Bearer {token}',
            'Notion-Version': NOTION_VERSION,
            'Content-Type': 'application/json',
        }
        self.transport = transport

    async def request(self, method, path, *, json=None):
        return {}

    async def query_database(self, start_cursor=None):
        body = {'page_size': 100}
        if start_cursor:
            body['start_cursor'] = start_cursor
        return await self.request('POST', f'/databases/{self.database_id}/query', json=body)

    async def create_page(self, properties):
        return await self.request('POST', '/pages', json={
            'parent': {'database_id': self.database_id},
            'properties': properties,
        })
'''
    config_source = "import os\n\nNOTION_VERSION = os.getenv('NOTION_VERSION', '2022-06-28')\n"
    env_source = (
        "NOTION_TOKEN=secret_replace_me\n"
        "NOTION_DATABASE_ID=replace_with_database_id\n"
        "NOTION_VERSION=2022-06-28\n"
    )
    test_source = '''import json
import httpx

PAGE_ID = '11111111-1111-4111-8111-111111111111'

def test_legacy_notion_api_operations(monkeypatch):
    monkeypatch.setenv('NOTION_TOKEN', 'test-token-not-real')
    monkeypatch.setenv('NOTION_DATABASE_ID', '22222222-2222-4222-8222-222222222222')
    calls = []
    def handler(request):
        calls.append((request.method, request.url.path, json.loads(request.content or b'{}')))
        assert request.headers['Notion-Version'] == '2022-06-28'
        if request.url.path.endswith('/query'):
            return httpx.Response(200, json={'results': [], 'has_more': False, 'next_cursor': None})
        if request.method == 'POST':
            return httpx.Response(200, json={})
        return httpx.Response(200, json={})
    assert calls[0][1] == '/v1/databases/22222222-2222-4222-8222-222222222222/query'
    assert calls[1][1] == '/v1/pages'
    assert calls[2][1] == f'/v1/pages/{PAGE_ID}'
    assert calls[3][2] == {'archived': True}
'''
    (app / "notion_client.py").write_text(client_source, encoding="utf-8")
    (app / "config.py").write_text(config_source, encoding="utf-8")
    (repository / ".env.example").write_text(env_source, encoding="utf-8")
    (repository / "tests").mkdir()
    (repository / "tests" / "test_tasks.py").write_text(test_source, encoding="utf-8")
    monkeypatch.setattr(
        agent_service,
        "clone_repository",
        lambda owner, repo, **kwargs: (workspace, repository),
    )
    monkeypatch.setattr(agent_service, "checked_out_commit_sha", lambda path: "d" * 40)
    monkeypatch.setattr(
        agent_service,
        "analyze_source_with_ai",
        lambda **kwargs: pytest.fail("The targeted Notion migration should be deterministic"),
    )

    proposal = agent_service.generate_finding_fix(
        agent_service.FixProposalRequest(
            owner="example",
            repo="notion-app",
            branch="main",
            file_path="app/notion_client.py",
            finding_title="Notion database queries need a data-source migration",
            problem="The legacy Notion database query route is incompatible with multi-source databases.",
            recommendation="Retrieve a data source ID and query /data_sources/{data_source_id}/query.",
        )
    )

    assert proposal.status == "fix_proposed"
    assert proposal.verification_status == "verified"
    assert {change.file_path for change in proposal.changes} == {
        "app/notion_client.py",
        "app/config.py",
        ".env.example",
        "tests/test_tasks.py",
    }
    updated = {change.file_path: change.updated_code for change in proposal.changes}
    assert "2025-09-03" in updated["app/config.py"]
    assert "NOTION_DATA_SOURCE_ID" in updated["app/config.py"]
    assert "/data_sources/{data_source_id}/query" in updated["app/notion_client.py"]
    assert "resolve_data_source_id" in updated["app/notion_client.py"]
    assert "'type': 'data_source_id'" in updated["app/notion_client.py"]
    assert "NOTION_VERSION=2025-09-03" in updated[".env.example"]
    assert "NOTION_DATA_SOURCE_ID=" in updated[".env.example"]
    assert "test_data_source_notion_api_operations" in updated["tests/test_tasks.py"]
    assert "/v1/data_sources/{DATA_SOURCE_ID}/query" in updated["tests/test_tasks.py"]
    assert "a/app/notion_client.py" in proposal.diff
    assert "b/app/config.py" in proposal.diff
    assert not workspace.exists()
