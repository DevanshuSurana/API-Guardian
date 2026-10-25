import json

from services.api_detection_service import (
    collect_dependency_context,
    detect_api_usages,
    detect_figma_compatibility_issues,
    detect_notion_legacy_migration,
    notion_legacy_version_configured,
)


def test_detects_notion_sdk_call_and_attaches_dependency_version(tmp_path):
    (tmp_path / "package.json").write_text(
        json.dumps({"dependencies": {"@notionhq/client": "^4.0.0"}})
    )
    (tmp_path / "src").mkdir()
    source = "const result = await notion.databases.query({ database_id });\n"

    context, versions = collect_dependency_context(tmp_path)
    usages = detect_api_usages(source, "src/tasks.js", "main", versions)

    assert "@notionhq/client" in context
    assert len(usages) == 1
    assert usages[0].provider == "Notion"
    assert usages[0].dependency_version == "^4.0.0"
    assert "notion.databases.query" in usages[0].evidence


def test_detects_common_http_api_calls():
    usages = detect_api_usages(
        "response = httpx.get('https://service.example/v1/items')\n",
        "client.py",
        "main",
        {"httpx": "0.27.2"},
    )

    assert len(usages) == 1
    assert usages[0].provider == "HTTPX"
    assert usages[0].dependency_version == "0.27.2"


def test_ignores_local_and_indirect_fetch_calls():
    source = "fetch('/api/tasks'); fetch(path); fetch(\"./config.json\");"

    usages = detect_api_usages(source, "static/app.js", "main", {})

    assert usages == []


def test_detects_fetch_to_absolute_external_url():
    usages = detect_api_usages(
        "fetch('https://api.example.com/v1/tasks');",
        "static/app.js",
        "main",
        {},
    )

    assert [usage.provider for usage in usages] == ["Fetch API"]


def test_flags_legacy_notion_database_query_with_actionable_migration():
    source = """
NOTION_VERSION = "2022-06-28"
url = f"https://api.notion.com/v1/databases/{database_id}/query"
"""
    finding = detect_notion_legacy_migration(source)

    assert finding is not None
    assert finding["severity"] == "medium"
    assert "data_source_id" in finding["recommendation"]
    assert "single-source" in finding["explanation"]


def test_does_not_flag_notion_version_without_legacy_query_route():
    source = 'NOTION_VERSION = "2022-06-28"\nurl = "/v1/pages"\n'
    assert detect_notion_legacy_migration(source) is None


def test_ignores_old_notion_route_text_in_docstrings_and_comments():
    source = '''
"""Notion-Version: 2022-06-28 used POST /v1/databases/{database_id}/query."""
# Legacy route: POST /v1/databases/{database_id}/query
NOTION_VERSION = "2025-09-03"
url = f"https://api.notion.com/v1/data_sources/{data_source_id}/query"
'''

    assert detect_notion_legacy_migration(source, file_path="app/notion_client.py") is None


def test_detects_notion_legacy_route_using_version_from_separate_config():
    config = "NOTION_VERSION = os.getenv('NOTION_VERSION', '2022-06-28')\n"
    client = '''
async def query(self, database_id):
    return await self.request("POST", f"/databases/{database_id}/query")
'''

    assert notion_legacy_version_configured(config)
    finding = detect_notion_legacy_migration(
        client,
        legacy_version_configured=True,
        file_path="app/notion_client.py",
    )
    assert finding is not None
    assert "NOTION_VERSION defaults" in finding["evidence"]


def test_ignores_notion_migration_text_in_non_python_file():
    source = '"Notion-Version: 2022-06-28" /v1/databases/{database_id}/query'
    assert detect_notion_legacy_migration(source, file_path="README.md") is None


def test_detects_and_fixes_figma_file_nodes_query_parameter():
    source = '''async def get_nodes(self, key, node_ids):
    return await self.request(
        f"/files/{extract_file_key(key)}/nodes",
        {"node_ids": ",".join(node_ids)},
    )
'''

    findings = detect_figma_compatibility_issues(source, "figma_client.py")

    assert len(findings) == 1
    assert findings[0]["severity"] == "high"
    assert '"ids": ",".join(node_ids)' in findings[0]["proposed_code"]
    assert '"node_ids":' not in findings[0]["proposed_code"]
    assert '"/files/{extract_file_key(key)}/nodes"' in findings[0]["proposed_code"]


def test_fixes_the_full_figma_get_nodes_method_with_validation():
    source = '''import re

class FigmaError(Exception):
    pass

def extract_file_key(key):
    return key

class FigmaClient:
    async def get_nodes(self, key, node_ids):
        # REQUEST 2: Incorrect Figma API query parameter
        # BUG: node_ids should be ids
        if not node_ids or len(node_ids) > 10 or any(
            not re.fullmatch(r'[0-9]+:[0-9]+', node)
            for node in node_ids
        ):
            raise FigmaError(
                'Provide 1-10 valid Figma node IDs (e.g. 1:2).',
                400
            )

        return await self.request(
            f'/files/{extract_file_key(key)}/nodes',
            {'node_ids': ','.join(node_ids)}
        )
'''

    findings = detect_figma_compatibility_issues(source, "figma_client.py")

    assert len(findings) == 1
    assert findings[0]["title"] == "Figma nodes call uses `node_ids` instead of `ids`"
    assert "'ids': ','.join(node_ids)" in findings[0]["proposed_code"]
    assert "'node_ids': ','.join(node_ids)" not in findings[0]["proposed_code"]
    assert "re.fullmatch" in findings[0]["proposed_code"]
    assert "Provide 1-10 valid Figma node IDs" in findings[0]["proposed_code"]


def test_does_not_flag_correct_figma_ids_parameter():
    source = '''async def get_nodes(self, key, node_ids):
    return await self.request(
        f"/files/{key}/nodes",
        {"ids": ",".join(node_ids)},
    )
'''

    assert detect_figma_compatibility_issues(source, "figma_client.py") == []


def test_detects_and_fixes_figma_singular_file_endpoint():
    source = '''BASE_URL = "https://api.figma.com/v1"

async def get_file(self, key):
    return await self.request(f"/file/{key}", {"depth": 2})
'''

    findings = detect_figma_compatibility_issues(source, "figma_client.py")

    assert len(findings) == 1
    assert findings[0]["title"] == "Figma file request uses `/file/` instead of `/files/`"
    assert 'f"/files/{key}"' in findings[0]["proposed_code"]


def test_combines_fixes_for_both_figma_endpoint_bugs():
    source = '''BASE_URL = "https://api.figma.com/v1"

async def get_file(self, key):
    return await self.request(f"/file/{key}", {"depth": 2})

async def get_nodes(self, key, node_ids):
    return await self.request(f"/files/{key}/nodes", {"node_ids": ",".join(node_ids)})
'''

    findings = detect_figma_compatibility_issues(source, "figma_client.py")

    assert {finding["title"] for finding in findings} == {
        "Figma file request uses `/file/` instead of `/files/`",
        "Figma nodes call uses `node_ids` instead of `ids`",
    }
    assert len({finding["proposed_code"] for finding in findings}) == 1
    combined_fix = findings[0]["proposed_code"]
    assert 'f"/files/{key}"' in combined_fix
    assert '"ids": ",".join(node_ids)' in combined_fix
    assert '"node_ids":' not in combined_fix
