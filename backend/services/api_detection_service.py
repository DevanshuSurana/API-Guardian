"""Detect common API clients and collect pinned dependency versions."""

from __future__ import annotations

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


def detect_notion_legacy_migration(source_code: str) -> dict[str, str] | None:
    """Return actionable, conditional guidance for Notion's 2025 API migration.

    Notion keeps older API versions working for existing single-source
    databases, so this is a compatibility risk rather than an unconditional
    breakage. The risk becomes concrete when a database gains another source.
    """
    version = re.search(
        r"(?:Notion-Version|NOTION_VERSION)\s*[:=]\s*[\"']?(2022-06-28)",
        source_code,
        re.IGNORECASE,
    )
    query_path = re.search(
        r"/v1/databases/[^\s\"'`]+/query|databases/\{[^}]+\}/query",
        source_code,
        re.IGNORECASE,
    )
    if not version or not query_path:
        return None
    return {
        "evidence": version.group(0),
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
