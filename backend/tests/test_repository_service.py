from git import Repo

from services.repository_service import (
    checkout_repository_branch,
    list_source_files,
    repository_branches,
)


def test_list_source_files_has_no_file_count_cap(tmp_path):
    repository = tmp_path / "repo"
    repository.mkdir()
    for index in range(205):
        (repository / f"module_{index:03}.py").write_text("pass\n")

    files = list_source_files(repository)

    assert len(files) == 205
    assert "module_204.py" in files


def test_list_source_files_includes_common_languages_and_tracked_build_outputs(
    tmp_path,
):
    expected_files = [
        "backend/client.py",
        "dist/app.js",
        "functions/handler.go",
        "native/client.rs",
        "server/Controller.cs",
        "web/component.vue",
    ]
    for relative_path in expected_files:
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("client.call()\n", encoding="utf-8")

    environment_source = tmp_path / ".venv314/lib/python/site.py"
    environment_source.parent.mkdir(parents=True)
    environment_source.write_text("client.call()\n", encoding="utf-8")
    dependency_source = tmp_path / "node_modules/pkg/index.js"
    dependency_source.parent.mkdir(parents=True)
    dependency_source.write_text("client.call()\n", encoding="utf-8")

    files = list_source_files(tmp_path)

    assert files == sorted(expected_files)


def test_remote_branches_are_listed_and_can_be_checked_out(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    working = Repo.init(source, initial_branch="main")
    with working.config_writer() as config:
        config.set_value("user", "name", "API Guardian Tests")
        config.set_value("user", "email", "tests@example.com")
    (source / "main.py").write_text("main = True\n")
    working.index.add(["main.py"])
    working.index.commit("main commit")
    working.git.checkout("-b", "feature/next")
    (source / "feature.py").write_text("feature = True\n")
    working.index.add(["feature.py"])
    working.index.commit("feature commit")

    bare = tmp_path / "remote.git"
    Repo.clone_from(str(source), str(bare), bare=True)
    clone = tmp_path / "clone"
    Repo.clone_from(
        str(bare),
        str(clone),
        depth=1,
        multi_options=["--no-single-branch"],
    )

    branches = repository_branches(clone)
    assert branches == ["feature/next", "main"]

    checkout_repository_branch(clone, "feature/next")

    assert (clone / "feature.py").is_file()
