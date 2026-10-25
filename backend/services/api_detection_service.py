"""Detect common API clients and collect pinned dependency versions."""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

from models.schemas import APIUsage

API_PATTERNS: dict[str, re.Pattern[str]] = {
    "Notion": re.compile(
        r"\b[A-Za-z_]\w*\s*\.\s*(?:databases|data_sources|pages|search)\s*\.\s*(?:query|retrieve|create|update|list)\s*\(",
        re.IGNORECASE,
    ),
    "Notion REST API": re.compile(
        r"api\.notion\.com|Notion-Version\s*[:=]", re.IGNORECASE
    ),
    "HTTPX": re.compile(
        r"\bhttpx\s*\.\s*(?:Client|AsyncClient|get|post|put|patch|delete|request)\s*\(",
        re.IGNORECASE,
    ),
    "Requests": re.compile(
        r"\brequests\s*\.\s*(?:Session|get|post|put|patch|delete|request)\s*\(",
        re.IGNORECASE,
    ),
    "Aiohttp": re.compile(
        r"\b(?:aiohttp\s*\.\s*ClientSession|session\s*\.\s*(?:get|post|put|patch|delete))\s*\(",
        re.IGNORECASE,
    ),
    # The Fetch API is filtered below: relative paths and indirection through
    # local helpers commonly represent this application's own backend routes.
    "Fetch API": re.compile(r"\bfetch\s*\(\s*([^,\)]+)", re.IGNORECASE),
    "Axios": re.compile(
        r"\baxios\s*\.\s*(?:get|post|put|patch|delete|request)\s*\(", re.IGNORECASE
    ),
    "OpenAI": re.compile(r"\b(?:OpenAI|AzureOpenAI|Anthropic)\s*\(", re.IGNORECASE),
    "GitHub API": re.compile(
        r"\b(?:Octokit|octokit\.(?:request|rest)|github\.get_repo)\b", re.IGNORECASE
    ),
    "AWS SDK": re.compile(r"\bboto3\.(?:client|resource)\s*\(", re.IGNORECASE),
}

MANIFEST_NAMES = {
    "requirements.txt",
    "requirements-dev.txt",
    "pyproject.toml",
    "Pipfile",
    "package.json",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "go.mod",
    "Cargo.toml",
    "Gemfile.lock",
    "pom.xml",
    "build.gradle",
    "composer.json",
}

DEPENDENCY_NAMES = {
    "notion": ("notion-client", "@notionhq/client"),
    "notion rest api": ("notion-client", "@notionhq/client"),
    "httpx": ("httpx",),
    "requests": ("requests",),
    "aiohttp": ("aiohttp",),
    "fetch api": (),
    "axios": ("axios",),
    "openai": ("openai",),
    "github api": ("@octokit/rest", "PyGithub"),
    "aws sdk": ("boto3", "@aws-sdk/"),
}


def collect_dependency_context(repository_path: Path) -> tuple[str, dict[str, str]]:
    """Read dependency manifests as context for the local audit model."""
    snippets: list[str] = []
    versions: dict[str, str] = {}
    files = sorted(
        path
        for path in repository_path.rglob("*")
        if path.is_file()
        and not path.is_symlink()
        and path.name in MANIFEST_NAMES
        and not any(
            part in {".git", "node_modules", ".venv", "venv"} for part in path.parts
        )
    )
    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        snippets.append(f"--- {path.relative_to(repository_path)} ---\n{text[:12000]}")
        if path.name in {"package.json", "package-lock.json"}:
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                continue
            sections = [payload]
            if "packages" in payload:
                sections.extend(payload["packages"].values())
            for section in sections:
                for group in ("dependencies", "devDependencies", "peerDependencies"):
                    for name, version in section.get(group, {}).items():
                        versions[name.lower()] = str(version)
        else:
            for line in text.splitlines():
                match = re.match(
                    r"\s*([A-Za-z0-9_.@/-]+)\s*(?:==|~=|>=|=)\s*([^;\s,]+)", line
                )
                if match:
                    versions[match.group(1).lower()] = match.group(2)
    return "\n".join(snippets), versions


def detect_api_usages(
    source_code: str,
    file_path: str,
    branch: str,
    dependency_versions: dict[str, str],
) -> list[APIUsage]:
    """Find concrete, source-backed API client call sites."""
    usages: list[APIUsage] = []
    for provider, pattern in API_PATTERNS.items():
        for match in pattern.finditer(source_code):
            if provider == "Fetch API":
                target = match.group(1).strip()
                # Only claim an external API when the call itself names an
                # absolute HTTP(S) URL. `fetch(path)` and `/api/...` are local
                # or ambiguous and should not be classified as third-party.
                if not re.match(r"^[\"']https?://", target, re.IGNORECASE):
                    continue
            package_names = DEPENDENCY_NAMES[provider.lower()]
            version = next(
                (
                    value
                    for package, value in dependency_versions.items()
                    if any(name.lower() in package for name in package_names)
                ),
                None,
            )
            start = max(0, match.start() - 80)
            end = min(len(source_code), match.end() + 160)
            evidence = " ".join(source_code[start:end].split())
            usages.append(
                APIUsage(
                    file_path=file_path,
                    branch=branch,
                    provider=provider,
                    evidence=evidence,
                    dependency_version=version,
                )
            )
    return usages


class _RemovePythonDocstrings(ast.NodeTransformer):
    """Remove module, class, and function docstrings before code inspection."""

    @staticmethod
    def _remove_docstring(node: ast.AST) -> ast.AST:
        body = getattr(node, "body", None)
        if (
            isinstance(body, list)
            and body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            node.body = body[1:]
        return node

    def visit_Module(self, node: ast.Module) -> ast.AST:
        self.generic_visit(node)
        return self._remove_docstring(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.AST:
        self.generic_visit(node)
        return self._remove_docstring(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
        self.generic_visit(node)
        return self._remove_docstring(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AST:
        self.generic_visit(node)
        return self._remove_docstring(node)


def _parse_executable_python(source_code: str) -> ast.Module | None:
    try:
        tree = ast.parse(source_code)
    except SyntaxError:
        return None
    return _RemovePythonDocstrings().visit(tree)


def _is_legacy_notion_version_configured(tree: ast.Module) -> bool:
    """Detect a real Python setting that defaults the Notion version to 2022."""
    for node in ast.walk(tree):
        value = None
        targets = []
        if isinstance(node, ast.Assign):
            targets = node.targets
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
            value = node.value
        if value is None or not any(
            isinstance(target, ast.Name) and target.id == "NOTION_VERSION"
            for target in targets
        ):
            continue
        if isinstance(value, ast.Constant) and value.value == "2022-06-28":
            return True
        if isinstance(value, ast.Call):
            function = value.func
            function_name = (
                function.id if isinstance(function, ast.Name)
                else function.attr if isinstance(function, ast.Attribute)
                else ""
            )
            if function_name in {"getenv", "get"} and any(
                isinstance(argument, ast.Constant)
                and argument.value == "2022-06-28"
                for argument in value.args[1:]
            ):
                return True
    return False


def notion_legacy_version_configured(source_code: str) -> bool:
    """Check a Python config module for an executable legacy Notion version."""
    tree = _parse_executable_python(source_code)
    return bool(tree and _is_legacy_notion_version_configured(tree))


def detect_notion_legacy_migration(
    source_code: str,
    *,
    legacy_version_configured: bool = False,
    file_path: str | None = None,
) -> dict[str, str] | None:
    """Return actionable, conditional guidance for Notion's 2025 API migration.

    Notion keeps older API versions working for existing single-source
    databases, so this is a compatibility risk rather than an unconditional
    breakage. The risk becomes concrete when a database gains another source.
    """
    if file_path and not file_path.lower().endswith(".py"):
        return None
    tree = _parse_executable_python(source_code)
    if tree is None:
        return None
    executable_source = ast.unparse(tree)
    version = re.search(
        r"(?:Notion-Version|NOTION_VERSION)\s*[:=]\s*[\"']?(2022-06-28)",
        executable_source,
        re.IGNORECASE,
    )
    has_legacy_version = bool(version) or legacy_version_configured
    query_path = re.search(
        r"/v1/databases/[^\s\"'`]+/query|databases/\{[^}]+\}/query",
        executable_source,
        re.IGNORECASE,
    )
    if not has_legacy_version or not query_path:
        return None
    return {
        "evidence": (
            version.group(0)
            if version
            else "NOTION_VERSION defaults to 2022-06-28 in repository configuration"
        ),
        "title": "Notion database queries need a data-source migration",
        "severity": "medium",
        "explanation": (
            "This code pins Notion API 2022-06-28 and uses the legacy database "
            "query route. Existing single-source databases may continue to work, "
            "but Notion documents that database read, write, and query calls "
            "using older versions fail if a second data source is added."
        ),
        "recommendation": (
            "Before using multi-source databases, send a 2025-09-03-or-newer "
            "Notion-Version, retrieve each database with GET /v1/databases/{database_id}, "
            "persist a data_source_id from its data_sources array, then query "
            "POST /v1/data_sources/{data_source_id}/query. Database IDs and "
            "data-source IDs are different; do not substitute one for the other. "
            "This needs a runtime ID-discovery step, so API Guardian cannot safely "
            "rewrite it as a blind text replacement."
        ),
    }


def detect_figma_compatibility_issues(
    source_code: str,
    file_path: str,
) -> list[dict[str, str]]:
    """Find known Figma file endpoint and file-nodes query mistakes.

    Figma documents ``GET /v1/files/:key`` and ``GET /v1/files/:key/nodes``;
    the file-nodes endpoint accepts the comma-separated ``ids`` query
    parameter. Only literal path segments and dictionary keys passed by the
    same call are rewritten. Dynamic parameter construction is left for a
    human to update.
    """
    if not file_path.lower().endswith(".py"):
        return []
    try:
        tree = ast.parse(source_code, filename=file_path)
    except SyntaxError:
        return []

    nodes_endpoint_pattern = re.compile(
        r"/(?:v\d+/)?files/[^'\"\s]+?/nodes(?=[/?#'\"\s]|$)",
        re.IGNORECASE,
    )
    singular_file_pattern = re.compile(r"/file/(?!s/)[^'\"\s]+", re.IGNORECASE)
    is_figma_source = bool(re.search(r"api\.figma\.com", source_code, re.IGNORECASE))
    lines = source_code.splitlines(keepends=True)
    edits: list[tuple[int, int, str]] = []
    issue_templates: list[dict[str, str]] = []
    seen_titles: set[str] = set()

    def source_offset(line_number: int, byte_column: int) -> int:
        line_index = line_number - 1
        line_start = sum(len(line) for line in lines[:line_index])
        prefix = lines[line_index].encode("utf-8")[:byte_column].decode("utf-8")
        return line_start + len(prefix)

    for call in ast.walk(tree):
        if not isinstance(call, ast.Call):
            continue
        call_source = ast.get_source_segment(source_code, call) or ""

        if is_figma_source:
            for nested in ast.walk(call):
                if not isinstance(nested, (ast.Constant, ast.JoinedStr)):
                    continue
                if isinstance(nested, ast.Constant) and not isinstance(nested.value, str):
                    continue
                segment = ast.get_source_segment(source_code, nested) or ""
                match = singular_file_pattern.search(segment)
                if not match:
                    continue
                start = source_offset(nested.lineno, nested.col_offset) + match.start()
                path = match.group(0)
                edits.append((start, start + len(path), path.replace("/file/", "/files/", 1)))
                title = "Figma file request uses `/file/` instead of `/files/`"
                if title not in seen_titles:
                    seen_titles.add(title)
                    issue_templates.append({
                        "title": title,
                        "severity": "high",
                        "evidence": " ".join(call_source.split()),
                        "explanation": (
                            "Figma documents the file endpoint as `/v1/files/:key` "
                            "with plural `files`. The singular `/file/:key` path "
                            "is an invalid endpoint and can return 404."
                        ),
                        "recommendation": (
                            "Replace `/file/` with `/files/` in the Figma request path."
                        ),
                    })
                break

        if nodes_endpoint_pattern.search(call_source):
            for nested in ast.walk(call):
                if not isinstance(nested, ast.Dict):
                    continue
                for key in nested.keys:
                    if not isinstance(key, ast.Constant) or key.value != "node_ids":
                        continue
                    key_source = ast.get_source_segment(source_code, key)
                    if not key_source:
                        continue
                    start = source_offset(key.lineno, key.col_offset)
                    edits.append((start, start + len(key_source), key_source.replace("node_ids", "ids", 1)))
                    title = "Figma nodes call uses `node_ids` instead of `ids`"
                    if title not in seen_titles:
                        seen_titles.add(title)
                        issue_templates.append({
                            "title": title,
                            "severity": "high",
                            "evidence": " ".join(call_source.split()),
                            "explanation": (
                                "Figma's file-nodes endpoint expects the `ids` query "
                                "parameter. `node_ids` is an invalid query parameter "
                                "for this endpoint and can make the request fail."
                            ),
                            "recommendation": (
                                "Rename the query parameter from `node_ids` to `ids`; "
                                "keep the comma-separated node ID value unchanged."
                            ),
                        })
                    break

    if not edits:
        return []

    updated_code = source_code
    for start, end, replacement in sorted(edits, key=lambda item: item[0], reverse=True):
        updated_code = updated_code[:start] + replacement + updated_code[end:]

    return [
        {**finding, "proposed_code": updated_code}
        for finding in issue_templates
    ]
