import asyncio

from models.schemas import FileChange, MigrationRequest
from services import agent_service


def test_analyze_migration_scans_and_cleans_repository(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    repository = workspace / "repository"
    source_path = repository / "src" / "client.py"
    source_path.parent.mkdir(parents=True)
    source_path.write_text("client.old_call()\n", encoding="utf-8")

    monkeypatch.setattr(
        agent_service,
        "clone_repository",
        lambda owner, repo: (workspace, repository),
    )
    proposed_change = FileChange(
        file_path="src/client.py",
        original_code="client.old_call()\n",
        updated_code="client.new_call()\n",
        explanation="The old call was removed.",
    )
    calls = []

    def analyze_file(**kwargs):
        calls.append(kwargs)
        return True, proposed_change

    monkeypatch.setattr(agent_service, "analyze_source_with_ai", analyze_file)

    result = asyncio.run(
        agent_service.analyze_migration(
            MigrationRequest(
                owner="example",
                repo="client",
                changelog="old_call was removed; use new_call instead.",
            )
        )
    )

    assert result.repository == "example/client"
    assert result.breaking_change is True
    assert result.affected_files == [proposed_change]
    assert result.status == "analysis_complete"
    assert len(calls) == 1
    assert not workspace.exists()


def test_analyze_migration_limits_model_calls(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    repository = workspace / "repository"
    repository.mkdir(parents=True)
    relative_paths = []
    for index in range(agent_service.MAX_AI_ANALYSIS_FILES + 1):
        relative_path = f"src/client_{index}.py"
        source_path = repository / relative_path
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_text("def unchanged():\n    return True\n", encoding="utf-8")
        relative_paths.append(relative_path)

    monkeypatch.setattr(
        agent_service,
        "clone_repository",
        lambda owner, repo: (workspace, repository),
    )
    monkeypatch.setattr(
        agent_service,
        "list_source_files",
        lambda path: relative_paths,
    )
    analyzed = []

    def analyze_file(**kwargs):
        analyzed.append(kwargs["file_path"])
        return False, None

    monkeypatch.setattr(agent_service, "analyze_source_with_ai", analyze_file)

    result = asyncio.run(
        agent_service.analyze_migration(
            MigrationRequest(
                owner="example",
                repo="client",
                changelog="A new optional argument was added.",
            )
        )
    )

    assert len(analyzed) == agent_service.MAX_AI_ANALYSIS_FILES
    assert result.status == "analysis_limited"
    assert "Skipped 1 files" in result.summary
    assert result.breaking_change is False
    assert result.affected_files == []
    assert not workspace.exists()
