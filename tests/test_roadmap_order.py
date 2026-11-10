"""
Roadmap order keywords: waves, the critical path, cycles, the story table, and the CLI.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from devops_tools import roadmap_order as ORDER
from devops_tools.models import RoadmapIssue


def write_story_file(stories_directory: Path, file_name: str, text: str) -> None:
    stories_directory.mkdir(parents=True, exist_ok=True)
    (stories_directory / file_name).write_text(text, encoding="utf-8")


def write_issue(issue_id: str, status: str, needs: str) -> str:
    return f"#### {issue_id} Title of {issue_id}\n- Status: {status}\n- Needs: {needs}\n- Do: x\n\n"


@pytest.fixture
def stories_directory(tmp_path: Path) -> Path:
    """
    Two stories: AB-01 done, AB-02 and CD-01 ready, AB-03 after AB-02, CD-02 after AB-03 and
    CD-01, and a dropped issue that blocks nothing.
    """
    directory = tmp_path / "docs" / "stories"
    write_story_file(
        directory,
        "01-first.md",
        "## AB First story\n\n"
        + write_issue("AB-02", "todo", "AB-01")
        + write_issue("AB-03", "doing", "AB-02")
        + write_issue("AB-04", "dropped", "AB-03"),
    )
    write_story_file(
        directory,
        "02-second.md",
        "## CD Second story\n\n"
        + write_issue("CD-01", "review", "—")
        + write_issue("CD-02", "todo", "AB-03, CD-01")
        + write_issue("CD-03", "todo", "—"),
    )
    write_story_file(
        directory, "done.md", "## [01](01-first.md)\n\n" + write_issue("AB-01", "done", "—")
    )
    write_story_file(directory, "README.md", "## Order\n\nFocus: CD, AB\n")
    return directory


def test_compute_issue_waves_counts_open_blockers(stories_directory):
    """
    What: compute_issue_waves.
    When: issues need done, review, open, and dropped issues.
    Then: done and review count as finished, dropped issues get no wave, and each open issue
    is one wave after its latest open blocker.
    """
    issues_by_id, _ = ORDER.read_roadmap_issues(stories_directory)
    assert ORDER.compute_issue_waves(issues_by_id) == {
        "AB-02": 0,
        "AB-03": 1,
        "CD-02": 2,
        "CD-03": 0,
    }


def test_find_critical_path_follows_the_deepest_blockers(stories_directory):
    """
    What: find_critical_path.
    When: the deepest open issue waits on a chain of open issues.
    Then: the path runs from the first ready issue of that chain to the deepest issue.
    """
    issues_by_id, _ = ORDER.read_roadmap_issues(stories_directory)
    waves = ORDER.compute_issue_waves(issues_by_id)
    assert ORDER.find_critical_path(issues_by_id, waves) == ["AB-02", "AB-03", "CD-02"]


def test_an_unknown_needed_issue_blocks(stories_directory):
    """
    What: list_unfinished_needs.
    When: an issue needs an ID that no story file defines (a typo).
    Then: that ID counts as open, so the issue is not reported ready.
    """
    issues_by_id, _ = ORDER.read_roadmap_issues(stories_directory)
    typo_issue = RoadmapIssue("CD-09", "Typo", "CD", "todo", ("XY-01",))
    assert ORDER.list_unfinished_needs(typo_issue, issues_by_id) == ["XY-01"]


def test_a_dependency_cycle_is_reported(tmp_path):
    """
    What: compute_issue_waves.
    When: two open issues need each other.
    Then: it raises ValueError naming an issue on the cycle.
    """
    directory = tmp_path / "stories"
    write_story_file(
        directory,
        "01-loop.md",
        "## EF Loop\n\n"
        + write_issue("EF-01", "todo", "EF-02")
        + write_issue("EF-02", "todo", "EF-01"),
    )
    issues_by_id, _ = ORDER.read_roadmap_issues(directory)
    with pytest.raises(ValueError, match="dependency cycle through EF-0"):
        ORDER.compute_issue_waves(issues_by_id)


def test_build_story_table_marks_focus_ready_blocked_and_critical(stories_directory):
    """
    What: build_story_table.
    When: the focus is CD then AB, and CD's last issue waits on AB.
    Then: each story row has its earliest wave, `first (n)` in focus order, ready or blocked,
    critical when on the critical path, and its blocking stories.
    """
    issues_by_id, story_ids = ORDER.read_roadmap_issues(stories_directory)
    focus = ORDER.read_focus_story_ids((stories_directory / "README.md").read_text())
    assert focus == ["CD", "AB"]
    assert ORDER.build_story_table(issues_by_id, story_ids, focus).splitlines()[2:] == [
        "| 0 | AB | first (2), ready, critical | — | 2 |",
        "| 0 | CD | first (1), ready, critical | AB | 2 |",
    ]


def test_build_issue_view_lists_first_ready_and_blocked(stories_directory):
    """
    What: build_issue_view.
    When: the focus is CD then AB.
    Then: `first` lists the ready focus issues in focus order, and blocked issues name their
    blockers by wave.
    """
    issues_by_id, _ = ORDER.read_roadmap_issues(stories_directory)
    view = ORDER.build_issue_view(issues_by_id, ["CD", "AB"])
    first_section = view.split("first (ready, in focus order):\n")[1].split("\n\n")[0]
    assert first_section.splitlines() == ["  CD-03 Title of CD-03", "  AB-02 Title of AB-02"]
    assert "AB-03 blocked by AB-02" in view
    assert "CD-02 blocked by AB-03" in view


def test_main_write_then_check_uses_the_configured_paths(tmp_path, capsys):
    """
    What: the roadmap-order command.
    When: the settings move the stories, roadmap, and focus files, and the begin marker carries its
    own note.
    Then: check fails while stale, write fills the table and keeps the marker, and check then
    passes.
    """
    stories_directory = tmp_path / "plan" / "stories"
    write_story_file(
        stories_directory, "01-first.md", "## AB First\n\n" + write_issue("AB-01", "todo", "—")
    )
    (tmp_path / "plan" / "focus.md").write_text("Focus: AB\n")
    roadmap_path = tmp_path / "plan" / "roadmap.md"
    roadmap_path.write_text(
        "# Roadmap\n\n<!-- roadmap-order begin: any note here -->\nold\n"
        "<!-- roadmap-order end -->\n"
    )
    (tmp_path / "pyproject.toml").write_text(
        "[tool.devops-tools]\n"
        'stories-directory = "plan/stories"\n'
        'roadmap-file = "plan/roadmap.md"\n'
        'focus-file = "plan/focus.md"\n'
    )
    assert ORDER.main(["check", "--repository", str(tmp_path)]) == 1
    assert ORDER.main(["write", "--repository", str(tmp_path)]) == 0
    assert "| 0 | AB | first (1), ready, critical | — | 1 |" in roadmap_path.read_text()
    assert "<!-- roadmap-order begin: any note here -->" in roadmap_path.read_text()
    assert ORDER.main(["check", "--repository", str(tmp_path)]) == 0
    assert "order table is current" in capsys.readouterr().out


def test_main_write_without_markers_fails_and_changes_nothing(tmp_path, capsys):
    """
    What: the roadmap-order write command.
    When: the roadmap file has no begin and end markers.
    Then: it exits 1, says which markers are needed, and leaves the file unchanged.
    """
    write_story_file(
        tmp_path / "docs" / "stories",
        "01-first.md",
        "## AB First\n\n" + write_issue("AB-01", "todo", "—"),
    )
    (tmp_path / "docs" / "roadmap.md").write_text("# Roadmap\n")
    assert ORDER.main(["write", "--repository", str(tmp_path)]) == 1
    assert (tmp_path / "docs" / "roadmap.md").read_text() == "# Roadmap\n"
    assert "needs the markers" in capsys.readouterr().err


def test_read_roadmap_issues_follows_the_issue_id_pattern_setting(tmp_path):
    """
    What: read_roadmap_issues.
    When: the issue ID pattern requires two digits and a heading has one.
    Then: only the issue that matches the pattern is read.
    """
    write_story_file(
        tmp_path,
        "01-first.md",
        "## AB First\n\n"
        + write_issue("AB-01", "todo", "—")
        + write_issue("AB-2", "todo", "AB-01"),
    )
    issues_by_id, _ = ORDER.read_roadmap_issues(tmp_path, r"AB-[0-9]{2}")
    assert sorted(issues_by_id) == ["AB-01"]


def write_issue_file(issues_directory: Path, state: str, issue_id: str, text: str) -> None:
    directory = issues_directory / state
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{issue_id}.md").write_text(text, encoding="utf-8")


def test_per_issue_files_are_read_with_their_status_and_needs(tmp_path):
    """
    What: read_roadmap_issues with an issues directory.
    When: one issue is in the open directory and the one it needs is in the done directory.
    Then: both are read, the story order still comes from the story file headings, and the open
    issue is not blocked by the done one.
    """
    stories_directory = tmp_path / "stories"
    write_story_file(stories_directory, "01-first.md", "## AB First story\n")
    issues_directory = tmp_path / "issues"
    write_issue_file(issues_directory, "open", "AB-02", write_issue("AB-02", "todo", "AB-01"))
    write_issue_file(issues_directory, "done", "AB-01", write_issue("AB-01", "done", "—"))
    issues_by_id, story_ids = ORDER.read_roadmap_issues(
        stories_directory, issues_directory=issues_directory
    )
    assert sorted(issues_by_id) == ["AB-01", "AB-02"]
    assert story_ids == ["AB"]
    assert issues_by_id["AB-02"].needed_issue_ids == ("AB-01",)
    assert ORDER.list_unfinished_needs(issues_by_id["AB-02"], issues_by_id) == []


def test_missing_issue_directories_read_as_empty(tmp_path):
    """
    What: read_roadmap_issues with an issues directory.
    When: neither the open nor the done subdirectory exists yet.
    Then: only the story files are read and nothing fails.
    """
    stories_directory = tmp_path / "stories"
    write_story_file(
        stories_directory, "01-first.md", "## AB First\n\n" + write_issue("AB-01", "todo", "—")
    )
    issues_by_id, _ = ORDER.read_roadmap_issues(
        stories_directory, issues_directory=tmp_path / "issues"
    )
    assert list(issues_by_id) == ["AB-01"]
