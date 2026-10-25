"""Coordinate repository scanning with the local AI migration agent."""

from __future__ import annotations

import asyncio
import os
import re
import time

from git import Repo
from models.schemas import (
    APIFinding,
    APIUsage,
    FileChange,
    FixProposalRequest,
    FixProposalResponse,
    MigrationRequest,
    MigrationResponse,
)

from services.ai_integration_service import (
    analyze_source_with_ai,
    audit_source_for_api_issues,
    has_candidate_api_usage,
)
from services.api_detection_service import (
    collect_dependency_context,
    detect_api_usages,
    detect_notion_legacy_migration,
)
from services.mlflow_service import log_live_analysis
from services.patch_service import PatchError, generate_diff, validate_file_path
from services.repository_service import (
    checkout_repository_branch,
    cleanup_workspace,
    clone_repository,
    list_source_files,
    parse_github_repository_url,
    repository_branches,
)


def _repository_identity(request: MigrationRequest) -> tuple[str, str]:
    if request.repo_url:
        owner, repo = parse_github_repository_url(request.repo_url)
        if request.owner and request.owner != owner:
            raise ValueError("GitHub URL owner does not match the owner field")
        if request.repo and request.repo.removesuffix(".git") != repo:
            raise ValueError("GitHub URL repository does not match the repository field")
        return owner, repo
    if request.owner and request.repo:
        return request.owner, request.repo.removesuffix(".git")
    raise ValueError("Provide a GitHub repository URL")


def _analyze_repository(request: MigrationRequest) -> MigrationResponse:
    started_at = time.perf_counter()
    owner, repo = _repository_identity(request)
    workspace, repository_path = clone_repository(
        owner,
        repo,
        all_branches=request.all_branches,
        branch=request.branch,
    )
    try:
        analyzed_files = 0
        ai_reviewed_files = 0
        breaking_change = False
        affected_files: list[FileChange] = []
        findings: list[APIFinding] = []
        api_usages: list[APIUsage] = []
        branches = (
            repository_branches(repository_path)
            if request.all_branches
            else [request.branch or repository_branches(repository_path)[0]]
        )

        for branch in branches:
            checkout_repository_branch(repository_path, branch)
            dependency_context, dependency_versions = collect_dependency_context(
                repository_path
            )
            for relative_path in list_source_files(repository_path):
                source_path = repository_path / relative_path
                try:
                    source_code = source_path.read_text(
                        encoding="utf-8",
                        errors="replace",
                    )
                except OSError as error:
                    raise RuntimeError(
                        f"Could not read source file '{branch}:{relative_path}': {error}"
                    ) from error

                if not source_code.strip():
                    analyzed_files += 1
                    continue

                analyzed_files += 1
                detected = detect_api_usages(
                    source_code,
                    relative_path,
                    branch,
                    dependency_versions,
                )
                api_usages.extend(detected)

                if request.changelog.strip():
                    # Every supported source file is still read and statically
                    # inspected above. Avoid a slow local-model call when a
                    # parseable Python file has no call or keyword named by the
                    # changelog and no supported external API usage was found.
                    # Unknown languages and unparsable Python return None from
                    # the conservative prefilter and still go to the model.
                    candidate = has_candidate_api_usage(
                        source_code,
                        request.changelog,
                    )
                    if candidate is False and not detected:
                        continue

                    ai_reviewed_files += 1
                    file_breaking, change = analyze_source_with_ai(
                        changelog=request.changelog,
                        file_path=relative_path,
                        source_code=source_code,
                    )
                    breaking_change = breaking_change or file_breaking
                    if change is not None:
                        change.branch = branch
                        affected_files.append(change)
                    continue

                if not detected:
                    continue
                audit = audit_source_for_api_issues(
                    source_code,
                    relative_path,
                    dependency_context,
                )
                audit_findings = list(audit["findings"])
                notion_migration = detect_notion_legacy_migration(source_code)
                if notion_migration and not any(
                    item["title"] == notion_migration["title"]
                    for item in audit_findings
                ):
                    audit_findings.append({
                        **notion_migration,
                        "proposed_code": "",
                    })
                for item in audit_findings:
                    finding = APIFinding(
                        file_path=relative_path,
                        branch=branch,
                        severity=item["severity"],
                        title=item["title"],
                        evidence=item["evidence"],
                        explanation=item["explanation"],
                        recommendation=item["recommendation"],
                        proposed_code=item["proposed_code"] or None,
                    )
                    findings.append(finding)
                    if item["proposed_code"]:
                        affected_files.append(
                            FileChange(
                                file_path=relative_path,
                                original_code=source_code,
                                updated_code=item["proposed_code"],
                                explanation=(
                                    f"{item['title']}: {item['recommendation']}"
                                ),
                                branch=branch,
                            )
                        )

        if not request.changelog.strip():
            breaking_change = bool(findings)

        if request.changelog.strip():
            summary = (
                f"Analyzed {analyzed_files} source files; "
                f"AI reviewed {ai_reviewed_files} likely candidates; "
                f"proposed changes for {len(affected_files)} affected files."
            )
            if breaking_change and not affected_files:
                summary += (
                    " A breaking change was detected, but no unambiguous safe edit "
                    "was generated; no source files were changed."
                )
        else:
            providers = sorted({usage.provider for usage in api_usages})
            summary = (
                f"Scanned {analyzed_files} source files and found "
                f"{len(api_usages)} API call sites across {len(providers)} providers. "
                f"The audit reported {len(findings)} potential issues and proposed "
                f"{len(affected_files)} file fixes."
            )
            if providers:
                summary += f" APIs detected: {', '.join(providers)}."
            else:
                summary += " No supported external API client calls were detected."
        summary += f" Scanned {len(branches)} branches: {', '.join(branches)}."

        result = MigrationResponse(
            repository=f"{owner}/{repo}",
            breaking_change=breaking_change,
            affected_files=affected_files,
            summary=summary,
            status="analysis_complete",
            branches_scanned=branches,
            api_detected=bool(api_usages),
            api_usages=api_usages,
            findings=findings,
        )
        result.mlflow_run_id = log_live_analysis(
            repository=result.repository,
            breaking_change=result.breaking_change,
            affected_file_count=len(result.affected_files),
            status=result.status,
            duration_seconds=time.perf_counter() - started_at,
            model=os.getenv("OLLAMA_MODEL", "gemma3:4b"),
            file_paths=[change.file_path for change in result.affected_files],
        )
        return result
    finally:
        cleanup_workspace(workspace)


async def analyze_migration(request: MigrationRequest) -> MigrationResponse:
    """Clone and analyze a public repository without modifying it."""
    return await asyncio.to_thread(_analyze_repository, request)


def _notion_data_source_migration(
    repository_path,
    request: FixProposalRequest,
    branch: str,
) -> list[FileChange] | None:
    """Build a verified multi-file Notion 2025-09-03 migration when supported.

    The Notion version change requires more than swapping a URL: queries and
    page creation must use a data source ID. This targeted migration adds
    runtime discovery for single-source databases and an explicit environment
    override for databases with multiple data sources.
    """
    finding_context = (
        f"{request.finding_title} {request.problem} {request.recommendation}"
        .lower()
        .replace("-", " ")
    )
    if "notion" not in finding_context or "data source" not in finding_context:
        return None

    client_path = validate_file_path(str(repository_path), request.file_path)
    client_original = client_path.read_text(encoding="utf-8")
    client_source = client_original.replace(
        "Legacy Notion REST API adapter — intentional API Guardian migration target.",
        "Notion REST API adapter using data-source endpoints.",
    )
    if not re.search(r"/databases/\{self\.database_id\}/query", client_source):
        return None
    if "'parent': {'database_id': self.database_id}" not in client_source:
        return None

    config_relative = "app/config.py"
    try:
        config_path = validate_file_path(str(repository_path), config_relative)
    except PatchError:
        return None
    config_source = config_path.read_text(encoding="utf-8")
    version_pattern = re.compile(
        r"(?m)^(\s*NOTION_VERSION\s*=\s*os\.getenv\(\s*['\"]NOTION_VERSION['\"]\s*,\s*)"
        r"['\"]2022-06-28['\"](\s*\)\s*)$"
    )
    config_updated, version_count = version_pattern.subn(
        r"\g<1>'2025-09-03'\g<2>", config_source
    )
    if version_count != 1:
        return None
    data_source_setting = "NOTION_DATA_SOURCE_ID = os.getenv('NOTION_DATA_SOURCE_ID', '').strip()"
    if "NOTION_DATA_SOURCE_ID" not in config_updated:
        config_updated = config_updated.rstrip() + "\n\n" + data_source_setting + "\n"

    config_import = "from app.config import NOTION_API_BASE, NOTION_VERSION, notion_settings"
    if client_source.count(config_import) != 1:
        return None
    client_updated = client_source.replace(
        config_import,
        "from app.config import NOTION_API_BASE, NOTION_DATA_SOURCE_ID, NOTION_VERSION, notion_settings",
        1,
    )
    transport_marker = "        self.transport = transport\n"
    if client_updated.count(transport_marker) != 1:
        return None
    client_updated = client_updated.replace(
        transport_marker,
        transport_marker + "        self.data_source_id = NOTION_DATA_SOURCE_ID or None\n",
        1,
    )

    query_start = "    async def query_database(self, start_cursor=None):"
    create_start = "    async def create_page(self, properties):"
    if client_updated.count(query_start) != 1 or client_updated.count(create_start) != 1:
        return None
    query_start_index = client_updated.index(query_start)
    create_start_index = client_updated.index(create_start)
    if query_start_index >= create_start_index:
        return None
    replacement = '''    async def resolve_data_source_id(self):
        """Resolve and cache the data source used by this task database."""
        if self.data_source_id:
            return self.data_source_id
        database = await self.request('GET', f'/databases/{self.database_id}')
        data_sources = database.get('data_sources') or []
        if len(data_sources) != 1:
            raise HTTPException(
                status_code=503,
                detail=(
                    'Set NOTION_DATA_SOURCE_ID to the data source that stores tasks '
                    'when the database has multiple data sources.'
                ),
            )
        self.data_source_id = data_sources[0].get('id')
        if not self.data_source_id:
            raise HTTPException(
                status_code=502,
                detail='Notion returned a database without a usable data source ID.',
            )
        return self.data_source_id

    async def query_database(self, start_cursor=None):
        """Query the configured Notion data source."""
        data_source_id = await self.resolve_data_source_id()
        body = {'page_size': 100, 'sorts': [{'timestamp': 'created_time', 'direction': 'descending'}]}
        if start_cursor:
            body['start_cursor'] = start_cursor
        return await self.request('POST', f'/data_sources/{data_source_id}/query', json=body)

'''
    client_updated = (
        client_updated[:query_start_index]
        + replacement
        + client_updated[create_start_index:]
    )
    create_prefix = "    async def create_page(self, properties):\n        return await self.request('POST', '/pages', json={\n            'parent': {'database_id': self.database_id},\n"
    create_migrated = (
        "    async def create_page(self, properties):\n"
        "        data_source_id = await self.resolve_data_source_id()\n"
        "        return await self.request('POST', '/pages', json={\n"
        "            'parent': {'type': 'data_source_id', 'data_source_id': data_source_id},\n"
    )
    if client_updated.count(create_prefix) != 1:
        return None
    client_updated = client_updated.replace(create_prefix, create_migrated, 1)

    changes = [
        FileChange(
            file_path=request.file_path,
            original_code=client_original,
            updated_code=client_updated,
            explanation=(
                "Upgrade Notion database queries and page creation to data source IDs. "
                "A single data source is discovered automatically; set "
                "NOTION_DATA_SOURCE_ID when the database has multiple sources. "
                "Update any existing NOTION_VERSION environment override to 2025-09-03."
            ),
            branch=branch,
        ),
        FileChange(
            file_path=config_relative,
            original_code=config_source,
            updated_code=config_updated,
            explanation=(
                "Use Notion API 2025-09-03 and accept an explicit data source ID "
                "for databases with multiple sources."
            ),
            branch=branch,
        ),
    ]

    env_example = repository_path / ".env.example"
    if env_example.is_file() and not env_example.is_symlink():
        env_source = env_example.read_text(encoding="utf-8")
        env_updated, env_version_count = re.subn(
            r"(?m)^NOTION_VERSION=2022-06-28\s*$",
            "NOTION_VERSION=2025-09-03",
            env_source,
        )
        if env_version_count == 1:
            env_updated = env_updated.replace(
                "# This test application deliberately uses the legacy Notion API version.",
                "# Notion API 2025-09-03 supports databases with multiple data sources.",
            )
            if "NOTION_DATA_SOURCE_ID" not in env_updated:
                env_updated = env_updated.rstrip() + (
                    "\n# Optional: set when the database has multiple data sources.\n"
                    "NOTION_DATA_SOURCE_ID=\n"
                )
            changes.append(
                FileChange(
                    file_path=".env.example",
                    original_code=env_source,
                    updated_code=env_updated,
                    explanation=(
                        "Document the upgraded API version and optional data source "
                        "selection for multi-source databases."
                    ),
                    branch=branch,
                )
            )

    test_path = repository_path / "tests" / "test_tasks.py"
    if test_path.is_file() and not test_path.is_symlink():
        test_source = test_path.read_text(encoding="utf-8")
        test_updated = test_source
        test_replacements = [
            (
                "PAGE_ID = '11111111-1111-4111-8111-111111111111'\n",
                (
                "PAGE_ID = '11111111-1111-4111-8111-111111111111'\n"
                "DATA_SOURCE_ID = '33333333-3333-4333-8333-333333333333'\n"
                ),
            ),
            (
                "def test_legacy_notion_api_operations(monkeypatch):",
                "def test_data_source_notion_api_operations(monkeypatch):",
            ),
            (
                "    monkeypatch.setenv('NOTION_DATABASE_ID', '22222222-2222-4222-8222-222222222222')\n",
                (
                "    monkeypatch.setenv('NOTION_DATABASE_ID', '22222222-2222-4222-8222-222222222222')\n"
                "    monkeypatch.setattr('app.notion_client.NOTION_DATA_SOURCE_ID', None)\n"
                ),
            ),
            (
                "        calls.append((request.method, request.url.path, json.loads(request.content or b'{}')))\n",
                (
                "        calls.append((request.method, request.url.path, json.loads(request.content or b'{}')))\n"
                "        if request.method == 'GET' and request.url.path == '/v1/databases/22222222-2222-4222-8222-222222222222':\n"
                "            return httpx.Response(200, json={'data_sources': [{'id': DATA_SOURCE_ID, 'name': 'Tasks'}]})\n"
                ),
            ),
            (
                "        assert request.headers['Notion-Version'] == '2022-06-28'\n",
                "        assert request.headers['Notion-Version'] == '2025-09-03'\n",
            ),
            (
                (
                "    assert calls[0][1] == '/v1/databases/22222222-2222-4222-8222-222222222222/query'\n"
                "    assert calls[1][1] == '/v1/pages'\n"
                "    assert calls[2][1] == f'/v1/pages/{PAGE_ID}'\n"
                "    assert calls[3][2] == {'archived': True}\n"
                ),
                (
                "    assert calls[0][1] == '/v1/databases/22222222-2222-4222-8222-222222222222'\n"
                "    assert calls[1][1] == f'/v1/data_sources/{DATA_SOURCE_ID}/query'\n"
                "    assert calls[2][1] == '/v1/pages'\n"
                "    assert calls[2][2]['parent'] == {'type': 'data_source_id', 'data_source_id': DATA_SOURCE_ID}\n"
                "    assert calls[3][1] == f'/v1/pages/{PAGE_ID}'\n"
                "    assert calls[4][2] == {'archived': True}\n"
                ),
            ),
        ]
        if all(test_updated.count(before) == 1 for before, _ in test_replacements):
            for before, after in test_replacements:
                test_updated = test_updated.replace(before, after, 1)
            changes.append(
                FileChange(
                    file_path="tests/test_tasks.py",
                    original_code=test_source,
                    updated_code=test_updated,
                    explanation=(
                        "Update the offline tests to expect Notion API 2025-09-03, "
                        "data-source discovery, data-source queries, and page parents."
                    ),
                    branch=branch,
                )
            )
    return changes


def generate_finding_fix(request: FixProposalRequest) -> FixProposalResponse:
    """Generate and validate a patch for one selected audit finding."""
    owner, repo = _repository_identity(request)
    if not request.file_path.lower().endswith(".py"):
        raise ValueError(
            "The current code repair agent generates Python fixes only. "
            "This finding can still be reviewed manually."
        )

    workspace, repository_path = clone_repository(
        owner,
        repo,
        branch=request.branch,
    )
    try:
        source_path = validate_file_path(
            str(repository_path),
            request.file_path,
        )
        source_code = source_path.read_text(encoding="utf-8")
        branch = request.branch or Repo(repository_path).active_branch.name
        targeted_changes = _notion_data_source_migration(
            repository_path,
            request,
            branch,
        )
        if targeted_changes:
            diffs = [
                generate_diff(str(repository_path), change)
                for change in targeted_changes
            ]
            combined_diff = "\n".join(diff for diff in diffs if diff)
            if not combined_diff:
                raise ValueError("The proposed fix does not change any source files.")
            return FixProposalResponse(
                change=targeted_changes[0],
                changes=targeted_changes,
                diff=combined_diff,
                status="fix_proposed",
            )

        changelog = (
            f"API Guardian finding: {request.finding_title}\n"
            f"Problem: {request.problem}\n"
            f"Required remediation: {request.recommendation}\n"
            "Generate the smallest correct code migration for this specific "
            "finding. Preserve unrelated behavior and do not make speculative "
            "changes. If the remediation cannot be implemented safely from the "
            "available source context, return no affected edit."
        )
        if request.changelog.strip():
            changelog += f"\nAdditional API release notes: {request.changelog.strip()}"

        _, change = analyze_source_with_ai(
            changelog=changelog,
            file_path=request.file_path,
            source_code=source_code,
        )
        if change is None:
            raise ValueError(
                "The repair agent could not create a safe code edit for this finding. "
                "Review the recommendation and update the API change details."
            )

        change.branch = branch
        diff = generate_diff(str(repository_path), change)
        if not diff:
            raise ValueError("The proposed fix does not change the source file.")
        return FixProposalResponse(
            change=change,
            changes=[change],
            diff=diff,
            status="fix_proposed",
        )
    finally:
        cleanup_workspace(workspace)
