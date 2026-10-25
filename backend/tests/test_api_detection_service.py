import json

from services.api_detection_service import (
    collect_dependency_context,
    detect_api_usages,
    detect_notion_legacy_migration,
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
