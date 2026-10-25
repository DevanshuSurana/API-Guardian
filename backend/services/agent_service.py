"""Coordinate repository scanning with the local AI migration agent."""

from __future__ import annotations

import asyncio
import re
from logging import getLogger
from uuid import uuid4

from git import Repo
from models.schemas import (
    APIFinding,
    APIUsage,
    FileChange,
    FixProposalRequest,
    FixProposalResponse,
    MigrationRequest,
    MigrationResponse,
    ScannedRevision,
)

from services.ai_integration_service import (
    analyze_source_with_ai,
    audit_source_for_api_issues,
    has_candidate_api_usage,
)
from services.api_detection_service import (
    collect_dependency_context,
    detect_api_usages,
    detect_figma_compatibility_issues,
    detect_notion_legacy_migration,
    notion_legacy_version_configured,
)
from services.code_validation_service import (
    CodeValidationError,
    validate_generated_python_change,
)
from services.patch_service import PatchError, generate_diff, validate_file_path
from services.repository_service import (
    StaleRepositoryRevisionError,
    checked_out_commit_sha,
    checkout_repository_branch,
    cleanup_workspace,
    clone_repository,
    list_source_files,
    parse_github_repository_url,
    repository_branches,
)
from services.scan_history_service import (
    DEFAULT_DATABASE_PATH as SCAN_HISTORY_DATABASE_PATH,
)

logger = getLogger(__name__)
from services.scan_history_service import (
    record_scan_findings,
)

_ACTIONABLE_COMPATIBILITY_SIGNAL = re.compile(
    r"\b(?:deprecated|deprecation|removed|no longer supported|breaking(?:\s+change)?|"
    r"incompatib\w*|unsupported|invalid\s+(?:argument|parameter|endpoint|request|response)|"
    r"sunset|end[- ]of[- ]life|renamed|moved to|replaced by|will fail|fails when|"
    r"legacy (?:endpoint|route)|changed endpoint|changed route|new endpoint required|"
    r"data[- ]source migration|requires? (?:a )?migration|"
    r"(?:invalid|incorrect|unsupported|unknown) query parameter)\b",
    re.IGNORECASE,
)
_CONFIRMED_BREAKING_SIGNAL = re.compile(
    r"\b(?:removed|no longer supported|breaking(?:\s+change)?|incompatib\w*|"
    r"unsupported|invalid\s+(?:argument|parameter|endpoint|request|response)|"
    r"invalid query parameter|will fail|fails when|changed endpoint|changed route)\b",
    re.IGNORECASE,
)


def _finding_is_actionable(finding: dict) -> bool:
    """Discard advice that does not identify a compatibility risk."""
    description = " ".join(
        str(finding.get(field) or "")
        for field in ("title", "explanation", "recommendation")
    )
    return bool(_ACTIONABLE_COMPATIBILITY_SIGNAL.search(description))


def _calibrate_finding_severity(finding: dict) -> str:
    """Reserve high severity for explicit, evidenced compatibility breaks."""
    severity = str(finding.get("severity") or "info").lower()
    description = " ".join(
        str(finding.get(field) or "")
        for field in ("title", "explanation", "recommendation")
    )
    confirmed_break = bool(_CONFIRMED_BREAKING_SIGNAL.search(description))
    if severity == "critical":
        return "high" if confirmed_break else "medium"
    if severity == "high" and not confirmed_break:
        return "medium"
    return severity


def _figma_finding_is_covered_by_static_rule(
    finding: dict,
    figma_findings: list[dict[str, str]],
) -> bool:
    """Drop model findings that restate a known Figma rule imprecisely."""
    if not figma_findings:
        return False
    text = " ".join(
        str(finding.get(field) or "")
        for field in ("title", "evidence", "explanation", "recommendation")
    ).casefold()
    for static_finding in figma_findings:
        title = static_finding.get("title", "")
        if title == "Figma nodes call uses `node_ids` instead of `ids`":
            if "node_ids" in text and (
                "query parameter" in text
                or "parameter" in text
                or "figma" in text
            ):
                return True
        elif (
            title == "Figma file request uses `/file/` instead of `/files/`"
            and ("/file/" in text or "singular file endpoint" in text)
        ):
            return True
    return False


def _figma_repair_kind(request: FixProposalRequest) -> str | None:
    """Identify requests for known Figma endpoint/query rules."""
    text = (
        f"{request.finding_title} {request.problem} {request.recommendation}"
    ).casefold()
    if "figma" not in text:
        return None
    if "node_ids" in text or "query parameter" in text or "get_nodes" in text:
        return "nodes_query_parameter"
    if "/file/" in text or "file endpoint" in text or "file request" in text:
        return "file_endpoint"
    return None


def _validated_proposed_code(
    original_code: str,
    proposed_code: str | None,
    file_path: str,
) -> str | None:
    """Return a Python proposal only if it introduces no undefined names."""
    if (
        not proposed_code
        or proposed_code == original_code
        or not file_path.lower().endswith(".py")
    ):
        return None
    try:
        validate_generated_python_change(
            original_code,
            proposed_code,
            file_path,
        )
    except CodeValidationError:
        return None
    return proposed_code


def _normalized_finding_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.casefold()).strip()


def _verify_proposed_fixes(
    file_path: str,
    dependency_context: str,
    findings: list[dict],
) -> dict[str, tuple[str, str]]:
    """Re-run the matching detector against each proposed source version."""
    grouped: dict[str, list[str]] = {}
    for finding in findings:
        proposed_code = finding.get("proposed_code")
        if proposed_code:
            grouped.setdefault(proposed_code, []).append(str(finding["title"]))

    verification: dict[str, tuple[str, str]] = {}
    for proposed_code, titles in grouped.items():
        figma_findings = detect_figma_compatibility_issues(proposed_code, file_path)
        figma_titles = {finding["title"] for finding in figma_findings}
        notion_finding = detect_notion_legacy_migration(proposed_code)
        notion_still_detected = bool(notion_finding)
        generic_titles = [
            title for title in titles
            if not title.startswith("Figma ")
            and title != "Notion database queries need a data-source migration"
        ]

        follow_up_titles: set[str] = set()
        follow_up_error: str | None = None
        if generic_titles:
            try:
                follow_up = audit_source_for_api_issues(
                    proposed_code,
                    file_path,
                    dependency_context,
                )
                follow_up_titles = {
                    _normalized_finding_title(str(item.get("title") or ""))
                    for item in follow_up.get("findings", [])
                    if isinstance(item, dict)
                }
            except Exception as error:  # noqa: BLE001 - Keep the scan result usable.
                follow_up_error = str(error)

        for title in titles:
            if title.startswith("Figma "):
                if title in figma_titles:
                    verification[title] = (
                        "still_detected",
                        "The Figma compatibility detector still finds this problem in the proposed code.",
                    )
                else:
                    verification[title] = (
                        "verified",
                        "The Figma compatibility detector no longer finds this problem in the proposed code.",
                    )
            elif title == "Notion database queries need a data-source migration":
                if notion_still_detected:
                    verification[title] = (
                        "still_detected",
                        "The Notion migration detector still finds the legacy version and query route.",
                    )
                else:
                    verification[title] = (
                        "verified",
                        "The Notion migration detector no longer finds the legacy version and query route.",
                    )
            elif follow_up_error:
                verification[title] = (
                    "unverified",
                    f"The follow-up audit could not verify this proposal: {follow_up_error}",
                )
            elif _normalized_finding_title(title) in follow_up_titles:
                verification[title] = (
                    "still_detected",
                    "The follow-up audit still reports this finding in the proposed code.",
                )
            else:
                verification[title] = (
                    "recheck_passed",
                    "The follow-up audit did not repeat this finding. Review the diff before publishing.",
                )

    return verification


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
        scanned_revisions: list[ScannedRevision] = []
        branches = (
            repository_branches(repository_path)
            if request.all_branches
            else [request.branch or repository_branches(repository_path)[0]]
        )

        for branch in branches:
            checkout_repository_branch(repository_path, branch)
            scanned_revisions.append(
                ScannedRevision(
                    branch=branch,
                    commit_sha=checked_out_commit_sha(repository_path),
                )
            )
            dependency_context, dependency_versions = collect_dependency_context(
                repository_path
            )
            source_files = list_source_files(repository_path)
            legacy_notion_version_configured = False
            for config_relative_path in source_files:
                if not config_relative_path.lower().endswith(".py"):
                    continue
                try:
                    config_source = (repository_path / config_relative_path).read_text(
                        encoding="utf-8",
                        errors="replace",
                    )
                except OSError as error:
                    raise RuntimeError(
                        f"Could not read source file '{branch}:{config_relative_path}': {error}"
                    ) from error
                if notion_legacy_version_configured(config_source):
                    legacy_notion_version_configured = True
                    break

            for relative_path in source_files:
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
                        validated_code = _validated_proposed_code(
                            change.original_code,
                            change.updated_code,
                            relative_path,
                        )
                        if validated_code is not None:
                            change.branch = branch
                            affected_files.append(change)
                    continue

                figma_migrations = detect_figma_compatibility_issues(
                    source_code,
                    relative_path,
                )
                notion_migration = detect_notion_legacy_migration(
                    source_code,
                    legacy_version_configured=legacy_notion_version_configured,
                    file_path=relative_path,
                )
                if not detected and not figma_migrations and not notion_migration:
                    continue
                audit_findings = []
                if detected:
                    audit = audit_source_for_api_issues(
                        source_code,
                        relative_path,
                        dependency_context,
                    )
                    audit_findings.extend(
                        item
                        for item in audit["findings"]
                        if isinstance(item, dict)
                        and not _figma_finding_is_covered_by_static_rule(
                            item,
                            figma_migrations,
                        )
                    )
                for item in figma_migrations:
                    api_usage = APIUsage(
                        file_path=relative_path,
                        branch=branch,
                        provider="Figma REST API",
                        evidence=item["evidence"],
                    )
                    if not any(
                        usage.provider == api_usage.provider
                        and usage.file_path == api_usage.file_path
                        and usage.branch == api_usage.branch
                        and usage.evidence == api_usage.evidence
                        for usage in api_usages
                    ):
                        api_usages.append(api_usage)
                    if not any(
                        existing["title"] == item["title"]
                        for existing in audit_findings
                    ):
                        audit_findings.append(item)
                if notion_migration and not any(
                    item["title"] == notion_migration["title"]
                    for item in audit_findings
                ):
                    audit_findings.append({
                        **notion_migration,
                        "proposed_code": "",
                    })
                if notion_migration:
                    notion_usage = APIUsage(
                        file_path=relative_path,
                        branch=branch,
                        provider="Notion REST API",
                        evidence=notion_migration["evidence"],
                    )
                    if not any(
                        usage.provider == notion_usage.provider
                        and usage.file_path == notion_usage.file_path
                        and usage.branch == notion_usage.branch
                        and usage.evidence == notion_usage.evidence
                        for usage in api_usages
                    ):
                        api_usages.append(notion_usage)
                verification_by_title = _verify_proposed_fixes(
                    relative_path,
                    dependency_context,
                    audit_findings,
                )
                for item in audit_findings:
                    if not _finding_is_actionable(item):
                        continue
                    proposed_code = _validated_proposed_code(
                        source_code,
                        item.get("proposed_code"),
                        relative_path,
                    )
                    verification_status, verification_message = (
                        verification_by_title.get(
                            item["title"],
                            (
                                "no_fix",
                                "No safe, validated code proposal is available for this finding.",
                            ),
                        )
                        if proposed_code
                        else (
                            "no_fix",
                            "No safe, validated code proposal is available for this finding.",
                        )
                    )
                    finding = APIFinding(
                        file_path=relative_path,
                        branch=branch,
                        severity=_calibrate_finding_severity(item),
                        title=item["title"],
                        evidence=item["evidence"],
                        explanation=item["explanation"],
                        recommendation=item["recommendation"],
                        proposed_code=proposed_code,
                        verification_status=verification_status,
                        verification_message=verification_message,
                    )
                    findings.append(finding)
                    if proposed_code:
                        existing_change = next(
                            (
                                change
                                for change in affected_files
                                if change.file_path == relative_path
                                and change.branch == branch
                                and change.updated_code == proposed_code
                            ),
                            None,
                        )
                        if existing_change is None:
                            affected_files.append(
                                FileChange(
                                    file_path=relative_path,
                                    original_code=source_code,
                                    updated_code=proposed_code,
                                    explanation=(
                                        f"{item['title']}: {item['recommendation']}"
                                    ),
                                    branch=branch,
                                )
                            )

        if not request.changelog.strip():
            breaking_change = bool(findings)

        scan_id = uuid4().hex
        targeted_scan = bool(request.changelog.strip())
        resolved_findings: list[APIFinding] = []
        history_reconciled = False
        if targeted_scan:
            history_message = (
                "This targeted changelog scan does not resolve prior findings. "
                "Run a full audit of the same branch to confirm resolution."
            )
        else:
            history_message = None
        try:
            tracked_findings, resolved_records = record_scan_findings(
                f"{owner}/{repo}",
                scan_id,
                [revision.model_dump() for revision in scanned_revisions],
                findings,
                reconcile=not targeted_scan,
                database_path=SCAN_HISTORY_DATABASE_PATH,
            )
            findings = [APIFinding(**item) for item in tracked_findings]
            resolved_findings = [APIFinding(**item) for item in resolved_records]
            history_reconciled = not targeted_scan
            if not targeted_scan and resolved_records:
                history_message = (
                    f"Confirmed {len(resolved_records)} finding(s) resolved "
                    "on the scanned branch revision(s)."
                )
            elif not targeted_scan:
                history_message = "Finding history reconciled for every scanned branch."
        except Exception as error:
            logger.exception("Could not persist API Guardian scan history")
            history_message = (
                "This scan completed, but local finding history could not be updated: "
                f"{error}"
            )

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
            scanned_revisions=scanned_revisions,
            api_detected=bool(api_usages),
            api_usages=api_usages,
            findings=findings,
            resolved_findings=resolved_findings,
            scan_id=scan_id,
            history_reconciled=history_reconciled,
            history_message=history_message,
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
        branch = request.branch or Repo(repository_path).active_branch.name
        base_commit_sha = checked_out_commit_sha(repository_path)
        if (
            request.expected_commit_sha
            and base_commit_sha != request.expected_commit_sha
        ):
            raise StaleRepositoryRevisionError(
                "The repository branch changed after this scan. Run a fresh audit "
                "before generating a fix."
            )
        source_path = validate_file_path(
            str(repository_path),
            request.file_path,
        )
        source_code = source_path.read_text(encoding="utf-8")
        dependency_context, _dependency_versions = collect_dependency_context(
            repository_path
        )
        figma_repair_kind = _figma_repair_kind(request)
        if figma_repair_kind:
            title_by_kind = {
                "nodes_query_parameter": "Figma nodes call uses `node_ids` instead of `ids`",
                "file_endpoint": "Figma file request uses `/file/` instead of `/files/`",
            }
            figma_finding = next(
                (
                    finding
                    for finding in detect_figma_compatibility_issues(
                        source_code,
                        request.file_path,
                    )
                    if finding["title"] == title_by_kind[figma_repair_kind]
                ),
                None,
            )
            if figma_finding is None:
                raise ValueError(
                    "The Figma issue from this audit is no longer present in the "
                    "selected source file. Run a fresh audit before generating a fix."
                )
            try:
                validate_generated_python_change(
                    source_code,
                    figma_finding["proposed_code"],
                    request.file_path,
                )
            except CodeValidationError as error:
                raise ValueError(
                    "The deterministic Figma fix failed static Python checks: "
                    f"{error}. No files were changed."
                ) from error
            change = FileChange(
                file_path=request.file_path,
                original_code=source_code,
                updated_code=figma_finding["proposed_code"],
                explanation=(
                    f"{figma_finding['title']}: "
                    f"{figma_finding['recommendation']}"
                ),
                branch=branch,
            )
            diff = generate_diff(str(repository_path), change)
            if not diff:
                raise ValueError("The proposed fix does not change the source file.")
            verification = _verify_proposed_fixes(
                request.file_path,
                dependency_context,
                [{
                    "title": figma_finding["title"],
                    "proposed_code": change.updated_code,
                }],
            ).get(figma_finding["title"], (
                "unverified",
                "The Figma fix could not be rechecked.",
            ))
            return FixProposalResponse(
                change=change,
                changes=[change],
                diff=diff,
                status="fix_proposed",
                verification_status=verification[0],
                verification_message=verification[1],
                branch=branch,
                base_commit_sha=base_commit_sha,
            )

        targeted_changes = _notion_data_source_migration(
            repository_path,
            request,
            branch,
        )
        if targeted_changes:
            for change in targeted_changes:
                if not change.file_path.lower().endswith(".py"):
                    continue
                try:
                    validate_generated_python_change(
                        change.original_code,
                        change.updated_code,
                        change.file_path,
                    )
                except CodeValidationError as error:
                    raise ValueError(
                        "The generated Notion migration failed static Python checks: "
                        f"{error}. No files were changed."
                    ) from error
            diffs = [
                generate_diff(str(repository_path), change)
                for change in targeted_changes
            ]
            combined_diff = "\n".join(diff for diff in diffs if diff)
            if not combined_diff:
                raise ValueError("The proposed fix does not change any source files.")
            target_change = next(
                (
                    change for change in targeted_changes
                    if change.file_path == request.file_path
                ),
                None,
            )
            verification = (
                _verify_proposed_fixes(
                    request.file_path,
                    dependency_context,
                    [{
                        "title": request.finding_title,
                        "proposed_code": target_change.updated_code,
                    }],
                ).get(request.finding_title)
                if target_change
                else None
            )
            return FixProposalResponse(
                change=targeted_changes[0],
                changes=targeted_changes,
                diff=combined_diff,
                status="fix_proposed",
                verification_status=verification[0] if verification else "unverified",
                verification_message=(
                    verification[1]
                    if verification
                    else "The targeted migration did not include the finding's source file, so it could not be rechecked."
                ),
                branch=branch,
                base_commit_sha=base_commit_sha,
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

        try:
            validate_generated_python_change(
                change.original_code,
                change.updated_code,
                change.file_path,
            )
        except CodeValidationError as error:
            raise ValueError(
                "The proposed fix failed static Python checks, so API Guardian "
                f"cannot prepare it for review: {error}. No files were changed."
            ) from error

        change.branch = branch
        diff = generate_diff(str(repository_path), change)
        if not diff:
            raise ValueError("The proposed fix does not change the source file.")
        verification = _verify_proposed_fixes(
            request.file_path,
            dependency_context,
            [{
                "title": request.finding_title,
                "proposed_code": change.updated_code,
            }],
        ).get(request.finding_title, (
            "unverified",
            "The proposed change could not be rechecked.",
        ))
        return FixProposalResponse(
            change=change,
            changes=[change],
            diff=diff,
            status="fix_proposed",
            verification_status=verification[0],
            verification_message=verification[1],
            branch=branch,
            base_commit_sha=base_commit_sha,
        )
    finally:
        cleanup_workspace(workspace)
