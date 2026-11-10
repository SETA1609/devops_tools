"""
Closing the issue of a merged pull request: the move to done, what stays open, and the roadmap.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from devops_tools import close_merged_issue as CLOSE

SETTINGS_TEXT = '[tool.devops-tools]\nissues-directory = "docs/issues"\n'
ROADMAP_TEXT = "# Roadmap\n\n<!-- roadmap-order begin -->\n\n<!-- roadmap-order end -->\n"


def write_issue_file(repository: Path, state: str, issue_id: str, status: str) -> Path:
    issue_file = repository / "docs" / "issues" / state / f"{issue_id}.md"
    issue_file.parent.mkdir(parents=True, exist_ok=True)
    issue_file.write_text(
        f"#### {issue_id} Title of {issue_id}\n- Status: {status}\n- Needs: —\n- Do: x\n",
        encoding="utf-8",
    )
    return issue_file


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    """
    A project with per-issue files, one story heading, and a roadmap with an empty table.
    """
    (tmp_path / "pyproject.toml").write_text(SETTINGS_TEXT, encoding="utf-8")
    stories_directory = tmp_path / "docs" / "stories"
    stories_directory.mkdir(parents=True)
    (stories_directory / "01-first.md").write_text("## AB First story\n", encoding="utf-8")
    (tmp_path / "docs" / "roadmap.md").write_text(ROADMAP_TEXT, encoding="utf-8")
    return tmp_path


def run_close(repository: Path, branch: str, pull_request_number: str = "7") -> int:
    return CLOSE.main(
        [
            "--repository",
            str(repository),
            "--branch",
            branch,
            "--pull-request-number",
            pull_request_number,
            "--merge-date",
            "2026-01-02",
        ]
    )


def test_an_issue_in_review_moves_to_done_with_its_merge_line(repository):
    """
    What: close-merged-issue.
    When: the merged branch names an issue whose status is review.
    Then: the open file is gone and the done file has Status done and the Merged line.
    """
    open_file = write_issue_file(repository, "open", "AB-01", "review")
    assert run_close(repository, "ab-01-some-slug") == 0
    assert not open_file.exists()
    done_text = (repository / "docs/issues/done/AB-01.md").read_text(encoding="utf-8")
    assert "- Status: done\n- Merged: #7, 2026-01-02\n- Needs: —\n" in done_text


def test_an_agent_branch_closes_its_issue(repository):
    """
    What: close-merged-issue.
    When: the branch is named agent/<name>/<issue-id>-<slug>.
    Then: the issue is found and moved.
    """
    write_issue_file(repository, "open", "AB-02", "review")
    assert run_close(repository, "agent/helper/ab-02-slug") == 0
    assert (repository / "docs/issues/done/AB-02.md").is_file()


@pytest.mark.parametrize("status", ["todo", "doing"])
def test_an_issue_not_in_review_stays_open(repository, status):
    """
    What: close-merged-issue.
    When: a merged pull request finishes only part of an issue, so its status is not review.
    Then: the issue stays in the open directory, unchanged.
    """
    open_file = write_issue_file(repository, "open", "AB-03", status)
    original_text = open_file.read_text(encoding="utf-8")
    assert run_close(repository, "ab-03-first-half") == 0
    assert open_file.read_text(encoding="utf-8") == original_text
    assert not (repository / "docs/issues/done/AB-03.md").exists()


def test_a_branch_without_an_issue_still_regenerates_the_roadmap(repository):
    """
    What: close-merged-issue.
    When: the merged branch names no issue and an open issue exists.
    Then: nothing moves, the run succeeds, and the roadmap table lists the open issue.
    """
    write_issue_file(repository, "open", "AB-04", "todo")
    assert run_close(repository, "update-readme") == 0
    assert "| AB |" in (repository / "docs/roadmap.md").read_text(encoding="utf-8")


def test_closing_the_last_open_issue_drops_it_from_the_roadmap(repository):
    """
    What: close-merged-issue.
    When: the only open issue of a story is closed.
    Then: the regenerated roadmap table has no row for that story.
    """
    write_issue_file(repository, "open", "AB-05", "review")
    assert run_close(repository, "ab-05-slug") == 0
    assert "| AB |" not in (repository / "docs/roadmap.md").read_text(encoding="utf-8")


def test_an_issue_already_in_done_is_an_error(repository):
    """
    What: close-merged-issue.
    When: the done directory already has a file for the issue in review.
    Then: the run fails and the open file is left in place.
    """
    open_file = write_issue_file(repository, "open", "AB-06", "review")
    write_issue_file(repository, "done", "AB-06", "done")
    assert run_close(repository, "ab-06-slug") == 1
    assert open_file.exists()


def test_a_run_for_a_closed_issue_changes_nothing(repository):
    """
    What: close-merged-issue, the retry after a lost push.
    When: the issue was already moved to done by an earlier run.
    Then: the run succeeds and the done file is unchanged.
    """
    write_issue_file(repository, "open", "AB-07", "review")
    assert run_close(repository, "ab-07-slug") == 0
    done_file = repository / "docs/issues/done/AB-07.md"
    closed_text = done_file.read_text(encoding="utf-8")
    assert run_close(repository, "ab-07-slug", "8") == 0
    assert done_file.read_text(encoding="utf-8") == closed_text


def test_a_malformed_merge_date_is_a_usage_error(repository):
    """
    What: close-merged-issue's arguments.
    When: --merge-date is not YYYY-MM-DD.
    Then: the run exits with the usage error code.
    """
    exit_code = CLOSE.main(
        [
            "--repository",
            str(repository),
            "--branch",
            "ab-01-slug",
            "--pull-request-number",
            "1",
            "--merge-date",
            "yesterday",
        ]
    )
    assert exit_code == CLOSE.EXIT_CODE_USAGE_ERROR


def test_a_project_without_issue_files_is_a_usage_error(repository):
    """
    What: close-merged-issue's settings.
    When: the issues-directory setting is not set.
    Then: the run exits with the usage error code.
    """
    (repository / "pyproject.toml").write_text("[tool.devops-tools]\n", encoding="utf-8")
    assert run_close(repository, "ab-01-slug") == CLOSE.EXIT_CODE_USAGE_ERROR
