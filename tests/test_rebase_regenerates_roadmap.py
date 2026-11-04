"""
rebase-open-branches with `regenerate-roadmap-on-rebase`: the generated story table in the
roadmap file is rebuilt from the rebased story files instead of being merged line by line.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from devops_tools import rebase_open_branches as REBASE
from devops_tools import roadmap_order as ORDER
from devops_tools.exceptions import RepositorySettingsError
from devops_tools.settings import read_repository_settings

ROADMAP_INTRO = "# Roadmap\n\nIntro line.\n\n"
STORY_HEADER = "## AB First story\n\n"


def git(repository: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", repository, *args],
        check=check,
        capture_output=True,
        text=True,
    )


def write(repository: Path, relative: str, text: str) -> None:
    path = repository / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_issue(issue_id: str, status: str) -> str:
    return f"#### {issue_id} Title of {issue_id}\n- Status: {status}\n- Needs: —\n- Do: x\n\n"


def write_stories(repository: Path, statuses: dict[str, str]) -> None:
    text = STORY_HEADER + "".join(write_issue(issue, status) for issue, status in statuses.items())
    write(repository, "docs/stories/01-first.md", text)


def regenerate_roadmap_and_commit(repository: Path, message: str) -> None:
    assert ORDER.main(["write", "--repository", str(repository)]) == 0
    git(repository, "add", "-A")
    git(repository, "commit", "-m", message)


def init_repository(tmp_path: Path, regenerate_setting: bool) -> Path:
    """
    A repository with three todo issues in story AB, a generated roadmap table, and the
    setting on or off.
    """
    repository = tmp_path / "repo"
    repository.mkdir()
    git(repository, "init", "-b", "main")
    git(repository, "config", "user.email", "test@example.com")
    git(repository, "config", "user.name", "Test")
    settings_text = "[tool.devops-tools]\n"
    if regenerate_setting:
        settings_text += "regenerate-roadmap-on-rebase = true\n"
    write(repository, "pyproject.toml", settings_text)
    write(repository, "CHANGELOG.md", "# Changelog\n\n## Unreleased\n")
    write(
        repository,
        "docs/roadmap.md",
        ROADMAP_INTRO + "<!-- roadmap-order begin -->\n<!-- roadmap-order end -->\n",
    )
    write_stories(repository, {"AB-01": "todo", "AB-02": "todo", "AB-03": "todo"})
    regenerate_roadmap_and_commit(repository, "Initial")
    return repository


def point_origin_at(repository: Path, *branches: str) -> None:
    for branch in branches:
        sha = git(repository, "rev-parse", branch).stdout.strip()
        git(repository, "update-ref", f"refs/remotes/origin/{branch}", sha)


def rebase_feature(repository: Path) -> int:
    point_origin_at(repository, "main", "feature")
    return REBASE.main(
        ["--repository", str(repository), "--branches", "feature", "--no-push", "--no-fetch"]
    )


def make_feature_and_main(
    repository: Path,
    feature_statuses: dict[str, str],
    main_statuses: dict[str, str],
) -> None:
    git(repository, "switch", "-c", "feature")
    write_stories(repository, feature_statuses)
    regenerate_roadmap_and_commit(repository, "Feature")
    git(repository, "switch", "main")
    write_stories(repository, main_statuses)
    regenerate_roadmap_and_commit(repository, "Main")


def roadmap_check_passes_on(repository: Path, branch: str) -> bool:
    git(repository, "switch", branch)
    try:
        return ORDER.main(["check", "--repository", str(repository)]) == 0
    finally:
        git(repository, "switch", "main")


def test_a_conflict_inside_the_generated_block_is_resolved_by_regenerating(tmp_path):
    """
    What: rebase-open-branches with regenerate-roadmap-on-rebase.
    When: the branch marks AB-01 in review (2 open) while main adds AB-04 (4 open), so the AB
    row conflicts.
    Then: the rebase succeeds and the branch's table is current (3 open).
    """
    repository = init_repository(tmp_path, regenerate_setting=True)
    make_feature_and_main(
        repository,
        {"AB-01": "review", "AB-02": "todo", "AB-03": "todo"},
        {"AB-01": "todo", "AB-02": "todo", "AB-03": "todo", "AB-04": "todo"},
    )
    assert rebase_feature(repository) == 0
    roadmap = git(repository, "show", "feature:docs/roadmap.md").stdout
    assert "<<<<<<<" not in roadmap
    assert "| AB |" in roadmap and roadmap.split("| AB |")[1].splitlines()[0].endswith("| 3 |")
    assert roadmap_check_passes_on(repository, "feature")


def test_a_clean_merge_that_leaves_the_table_stale_gets_a_regeneration_commit(tmp_path):
    """
    What: rebase-open-branches with regenerate-roadmap-on-rebase.
    When: the branch marks AB-01 and main marks AB-02 in review; both tables say 2 open, so
    git merges them cleanly into a stale table.
    Then: the branch gets a commit that regenerates the table, which then says 1 open.
    """
    repository = init_repository(tmp_path, regenerate_setting=True)
    make_feature_and_main(
        repository,
        {"AB-01": "review", "AB-02": "todo", "AB-03": "todo"},
        {"AB-01": "todo", "AB-02": "review", "AB-03": "todo"},
    )
    assert rebase_feature(repository) == 0
    subjects = git(repository, "log", "--format=%s", "main..feature").stdout.splitlines()
    assert subjects == ["Regenerate the roadmap order table", "Feature"]
    assert roadmap_check_passes_on(repository, "feature")


def test_no_regeneration_commit_when_the_table_is_already_current(tmp_path):
    """
    What: rebase-open-branches with regenerate-roadmap-on-rebase.
    When: the branch changes no story, only an unrelated file.
    Then: the rebased branch has only its own commit.
    """
    repository = init_repository(tmp_path, regenerate_setting=True)
    git(repository, "switch", "-c", "feature")
    write(repository, "src/app.txt", "value = 1;\n")
    git(repository, "add", "-A")
    git(repository, "commit", "-m", "Feature")
    git(repository, "switch", "main")
    write_stories(repository, {"AB-01": "review", "AB-02": "todo", "AB-03": "todo"})
    regenerate_roadmap_and_commit(repository, "Main")
    assert rebase_feature(repository) == 0
    subjects = git(repository, "log", "--format=%s", "main..feature").stdout.splitlines()
    assert subjects == ["Feature"]


def test_a_conflict_outside_the_generated_block_still_needs_a_person(tmp_path):
    """
    What: rebase-open-branches with regenerate-roadmap-on-rebase.
    When: both sides rewrite the roadmap's intro line differently.
    Then: the rebase fails and the branch is left where it was.
    """
    repository = init_repository(tmp_path, regenerate_setting=True)
    roadmap_path = repository / "docs/roadmap.md"
    git(repository, "switch", "-c", "feature")
    roadmap_path.write_text(roadmap_path.read_text().replace("Intro line.", "Branch intro."))
    git(repository, "commit", "-am", "Feature")
    git(repository, "switch", "main")
    roadmap_path.write_text(roadmap_path.read_text().replace("Intro line.", "Main intro."))
    git(repository, "commit", "-am", "Main")
    before = git(repository, "rev-parse", "feature").stdout
    assert rebase_feature(repository) == 1
    assert git(repository, "rev-parse", "feature").stdout == before


def test_without_the_setting_a_conflict_in_the_block_still_needs_a_person(tmp_path):
    """
    What: rebase-open-branches without regenerate-roadmap-on-rebase.
    When: the AB row conflicts as in the first test.
    Then: the rebase fails and the branch is left where it was.
    """
    repository = init_repository(tmp_path, regenerate_setting=False)
    make_feature_and_main(
        repository,
        {"AB-01": "review", "AB-02": "todo", "AB-03": "todo"},
        {"AB-01": "todo", "AB-02": "todo", "AB-03": "todo", "AB-04": "todo"},
    )
    before = git(repository, "rev-parse", "feature").stdout
    assert rebase_feature(repository) == 1
    assert git(repository, "rev-parse", "feature").stdout == before


def test_merge_roadmap_sides_takes_the_target_block_and_merges_the_rest():
    """
    What: merge_roadmap_sides.
    When: the blocks differ on all three sides and the branch adds a line after the block.
    Then: the result has the target's block and the branch's added line.
    """

    def roadmap(block: str, tail: str = "") -> str:
        return (
            ROADMAP_INTRO
            + f"<!-- roadmap-order begin -->\n\n{block}\n<!-- roadmap-order end -->\n{tail}"
        )

    merged = REBASE.merge_roadmap_sides(
        roadmap("base table\n"),
        roadmap("target table\n"),
        roadmap("branch table\n", "Branch note.\n"),
    )
    assert merged == roadmap("target table\n", "Branch note.\n")


def test_merge_roadmap_sides_refuses_a_file_without_markers():
    """
    What: merge_roadmap_sides.
    When: one side has no generated block markers.
    Then: it returns None, leaving the conflict.
    """
    assert REBASE.merge_roadmap_sides("# Roadmap\n", "# Roadmap\n", "# Other\n") is None


def test_read_repository_settings_reads_the_regenerate_setting(tmp_path):
    """
    What: read_repository_settings.
    When: regenerate-roadmap-on-rebase is true, and when it is absent.
    Then: the setting is True, and False by default.
    """
    (tmp_path / "pyproject.toml").write_text(
        "[tool.devops-tools]\nregenerate-roadmap-on-rebase = true\n"
    )
    assert read_repository_settings(tmp_path).regenerate_roadmap_on_rebase is True
    (tmp_path / "pyproject.toml").write_text("[tool.devops-tools]\n")
    assert read_repository_settings(tmp_path).regenerate_roadmap_on_rebase is False


@pytest.mark.parametrize("value_text", ['"yes"', "1", '["true"]'])
def test_read_repository_settings_rejects_a_regenerate_setting_that_is_not_a_boolean(
    tmp_path, value_text
):
    """
    What: read_repository_settings.
    When: regenerate-roadmap-on-rebase is a string, a number, or a list.
    Then: it raises RepositorySettingsError naming the key.
    """
    (tmp_path / "pyproject.toml").write_text(
        f"[tool.devops-tools]\nregenerate-roadmap-on-rebase = {value_text}\n"
    )
    with pytest.raises(RepositorySettingsError, match="regenerate-roadmap-on-rebase"):
        read_repository_settings(tmp_path)
