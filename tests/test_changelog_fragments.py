"""
Changelog fragments: validation, branch lookup, preview order, release, and settings.
"""

from __future__ import annotations

import datetime
import os
import subprocess
from pathlib import Path

import pytest

from devops_tools import changelog_fragments as FRAGMENTS
from devops_tools import models as MODELS

VALID_FRAGMENT = "### AB-19 Assemble the changelog\n\n- Adds fragments.\n"
CHANGELOG_TEXT = (
    "# Changelog\n\nLast updated: 2026-10-01T00:00Z\n\nIntro.\n\n"
    "## 2026-10-01\n\n### CD-01 Old (#1)\n\n- old\n"
)


def git(repository: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repository), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def write(repository: Path, relative: str, text: str) -> Path:
    path = repository / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def commit_all(repository: Path, message: str, unix_seconds: int) -> None:
    git(repository, "add", "-A")
    date = f"@{unix_seconds} +0000"
    subprocess.run(
        ["git", "-C", str(repository), "commit", "-q", "-m", message],
        check=True,
        env={
            **os.environ,
            "GIT_AUTHOR_DATE": date,
            "GIT_COMMITTER_DATE": date,
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@example.com",
        },
    )


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    repository = tmp_path / "repo"
    repository.mkdir()
    git(repository, "init", "-q", "-b", "main")
    write(repository, "CHANGELOG.md", CHANGELOG_TEXT)
    write(repository, "changes/README.md", "# Changelog fragments\n")
    commit_all(repository, "Initial", 1_000)
    return repository


# validate_changelog_fragment


def test_valid_fragment_has_no_problems():
    assert FRAGMENTS.validate_changelog_fragment("AB-19.md", VALID_FRAGMENT) == []


@pytest.mark.parametrize("file_name", ["AB1.1-02.md", "AB2-01.md", "EF-08.md"])
def test_story_ids_with_sub_numbers_and_b_milestones_are_valid(file_name: str):
    issue_id = file_name.removesuffix(".md")
    text = f"### {issue_id} Title\n\n- change\n"
    assert FRAGMENTS.validate_changelog_fragment(file_name, text) == []


@pytest.mark.parametrize("file_name", ["notes.md", "AB-1.md", "AB-19.txt", "AB-19-extra.md"])
def test_file_name_that_is_not_an_issue_id_is_rejected(file_name: str):
    problems = FRAGMENTS.validate_changelog_fragment(file_name, VALID_FRAGMENT)
    assert any("file name" in problem for problem in problems)


def test_heading_must_name_the_same_issue_as_the_file():
    problems = FRAGMENTS.validate_changelog_fragment("AB-20.md", VALID_FRAGMENT)
    assert any("AB-20" in problem and "heading" in problem for problem in problems)


def test_first_line_must_be_a_level_three_heading():
    problems = FRAGMENTS.validate_changelog_fragment("AB-19.md", "## AB-19 Title\n\n- change\n")
    assert any("heading" in problem for problem in problems)


def test_fragment_without_a_bullet_is_rejected():
    problems = FRAGMENTS.validate_changelog_fragment("AB-19.md", "### AB-19 Title\n\nProse only.\n")
    assert any("bullet" in problem for problem in problems)


def test_a_second_heading_is_rejected():
    text = VALID_FRAGMENT + "\n### AB-20 Another\n\n- more\n"
    problems = FRAGMENTS.validate_changelog_fragment("AB-19.md", text)
    assert any("heading" in problem for problem in problems)


@pytest.mark.parametrize("line", ["Status: review.", "Last updated: 2026-10-31T10:00Z"])
def test_status_and_last_updated_lines_are_rejected(line: str):
    text = f"### AB-19 Title\n\n{line}\n\n- change\n"
    problems = FRAGMENTS.validate_changelog_fragment("AB-19.md", text)
    assert any(line.split(":")[0] in problem for problem in problems)


def test_fragment_must_end_with_a_newline():
    problems = FRAGMENTS.validate_changelog_fragment("AB-19.md", VALID_FRAGMENT.rstrip("\n"))
    assert any("newline" in problem for problem in problems)


# Branch names and fragment lookup


@pytest.mark.parametrize(
    ("branch_name", "issue_id"),
    [
        ("ab-19-assemble-the-changelog-from-per-issue-fragments", "ab-19"),
        ("agent/claude/cd-04-pin-library", "cd-04"),
        ("ab1.1-02-read-bsa-header-and-record-directory", "ab1.1-02"),
        ("ab2-01-render-api", "ab2-01"),
        ("ab-19", "ab-19"),
    ],
)
def test_issue_id_is_read_from_the_branch_name(branch_name: str, issue_id: str):
    assert FRAGMENTS.find_issue_id_in_branch_name(branch_name) == issue_id


@pytest.mark.parametrize("branch_name", ["main", "feature/thing", "agent/claude/main", "release/1"])
def test_branch_without_an_issue_id_has_none(branch_name: str):
    assert FRAGMENTS.find_issue_id_in_branch_name(branch_name) is None


def test_fragment_is_found_for_a_lowercase_issue_id(tmp_path: Path):
    write(tmp_path, "AB2-01.md", "### AB2-01 Title\n\n- change\n")
    assert FRAGMENTS.find_fragment_for_issue(tmp_path, "ab2-01") == tmp_path / "AB2-01.md"
    assert FRAGMENTS.find_fragment_for_issue(tmp_path, "p2b-02") is None


def test_readme_is_not_a_fragment(repository: Path):
    write(repository, "changes/AB-19.md", VALID_FRAGMENT)
    paths = FRAGMENTS.list_changelog_fragment_paths(repository / "changes")
    assert paths == [repository / "changes" / "AB-19.md"]


def test_missing_changes_directory_has_no_fragments(tmp_path: Path):
    assert FRAGMENTS.list_changelog_fragment_paths(tmp_path / "changes") == []


# check_changelog_fragments


def test_check_passes_with_the_branch_fragment(repository: Path):
    write(repository, "changes/AB-19.md", VALID_FRAGMENT)
    assert FRAGMENTS.check_changelog_fragments(repository, "ab-19-assemble") == []


def test_check_reports_a_missing_fragment_for_the_branch(repository: Path):
    problems = FRAGMENTS.check_changelog_fragments(repository, "ab-19-assemble")
    assert any("changes/AB-19.md" in problem or "ab-19" in problem for problem in problems)


def test_check_reports_a_branch_without_an_issue_id(repository: Path):
    problems = FRAGMENTS.check_changelog_fragments(repository, "fix-things")
    assert any("fix-things" in problem for problem in problems)


def test_check_without_a_branch_only_validates(repository: Path):
    assert FRAGMENTS.check_changelog_fragments(repository, None) == []
    write(repository, "changes/AB-19.md", "### AB-19 Title\n")
    problems = FRAGMENTS.check_changelog_fragments(repository, None)
    assert any("AB-19.md" in problem for problem in problems)


def test_check_command_exits_1_on_problems(repository: Path, capsys):
    write(repository, "changes/oops.md", VALID_FRAGMENT)
    exit_code = FRAGMENTS.main(["--repository", str(repository), "check"])
    assert exit_code == 1
    assert "oops.md" in capsys.readouterr().out


# Commits and pull request numbers


@pytest.mark.parametrize(
    ("subject", "number"),
    [
        ("AB 18 rebase open pull requests onto main (#18)", 18),
        ("CD-04: Pin the library as a dependency (#11)", 11),
        ("AB-19: Define changelog fragments per issue", None),
        ("Mention (#3) in the middle", None),
    ],
)
def test_pull_request_number_is_read_from_a_squash_merge_subject(subject: str, number: int | None):
    assert FRAGMENTS.find_pull_request_number_in_subject(subject) == number


def test_added_commit_is_the_one_that_created_the_fragment(repository: Path):
    path = write(repository, "changes/AB-19.md", VALID_FRAGMENT)
    commit_all(repository, "AB 19 assemble the changelog (#23)", 2_000)
    write(repository, "changes/AB-19.md", VALID_FRAGMENT + "- edited later\n")
    commit_all(repository, "Edit the fragment (#24)", 3_000)
    commit = FRAGMENTS.find_fragment_added_commit(repository, path)
    assert commit is not None
    assert commit.committed_at_unix_seconds == 2_000
    assert commit.pull_request_number == 23


def test_uncommitted_fragment_has_no_added_commit(repository: Path):
    path = write(repository, "changes/AB-19.md", VALID_FRAGMENT)
    assert FRAGMENTS.find_fragment_added_commit(repository, path) is None


# Rendering and release


def make_fragment(issue_id: str, title: str = "Title") -> object:
    return MODELS.ChangelogFragment(
        path=Path(f"changes/{issue_id}.md"),
        issue_id=issue_id,
        title=title,
        text=f"### {issue_id} {title}\n\n- change {issue_id}\n",
    )


def make_commit(unix_seconds: int, number: int | None) -> object:
    return MODELS.FragmentCommit(
        commit_sha="0" * 40,
        committed_at_unix_seconds=unix_seconds,
        pull_request_number=number,
    )


def test_entries_are_newest_first_with_uncommitted_on_top():
    rendered = FRAGMENTS.render_changelog_entries(
        [
            (make_fragment("AB-19"), make_commit(1_000, 23)),
            (make_fragment("AB-21"), None),
            (make_fragment("AB-20"), make_commit(2_000, 24)),
        ],
        should_append_pull_request_numbers=False,
    )
    assert rendered.index("AB-21") < rendered.index("AB-20") < rendered.index("AB-19")
    assert "(#" not in rendered


def test_same_time_entries_are_ordered_by_issue_id():
    rendered = FRAGMENTS.render_changelog_entries(
        [
            (make_fragment("AB-20"), make_commit(1_000, None)),
            (make_fragment("AB-19"), make_commit(1_000, None)),
        ],
        should_append_pull_request_numbers=False,
    )
    assert rendered.index("AB-19") < rendered.index("AB-20")


def test_release_rendering_appends_known_pull_request_numbers():
    rendered = FRAGMENTS.render_changelog_entries(
        [
            (make_fragment("AB-19", "Assemble"), make_commit(1_000, 23)),
            (make_fragment("AB-20", "Check"), make_commit(500, None)),
        ],
        should_append_pull_request_numbers=True,
    )
    assert "### AB-19 Assemble (#23)\n" in rendered
    assert "### AB-20 Check\n" in rendered
    assert rendered.endswith("\n\n")


def test_release_section_goes_before_the_first_section():
    updated = FRAGMENTS.insert_release_section(
        CHANGELOG_TEXT, "2026-11-05", "### AB-19 New (#23)\n\n- new\n\n", "2026-11-05T12:00Z"
    )
    assert "Last updated: 2026-11-05T12:00Z\n" in updated
    assert updated.index("## 2026-11-05") < updated.index("## 2026-10-01")
    assert "Intro.\n\n## 2026-11-05\n\n### AB-19 New (#23)\n\n- new\n\n## 2026-10-01" in updated


def test_release_moves_fragments_and_deletes_them(repository: Path):
    write(repository, "changes/AB-19.md", "### AB-19 Assemble\n\n- fragments\n")
    commit_all(repository, "AB 19 assemble (#23)", 2_000)
    write(repository, "changes/AB-20.md", "### AB-20 Check pins\n\n- pins\n")
    commit_all(repository, "AB-20: Check pins (#24)", 3_000)
    now = datetime.datetime(2026, 11, 5, 12, 30, tzinfo=datetime.UTC)
    deleted = FRAGMENTS.release_changelog_fragments(repository, "2026-11-05", now)
    assert sorted(path.name for path in deleted) == ["AB-19.md", "AB-20.md"]
    assert FRAGMENTS.list_changelog_fragment_paths(repository / "changes") == []
    assert (repository / "changes" / "README.md").exists()
    changelog = (repository / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "Last updated: 2026-11-05T12:30Z" in changelog
    assert changelog.index("### AB-20 Check pins (#24)") < changelog.index(
        "### AB-19 Assemble (#23)"
    )
    assert changelog.index("### AB-19 Assemble (#23)") < changelog.index("## 2026-10-01")


def test_release_refuses_invalid_fragments(repository: Path):
    write(repository, "changes/AB-19.md", "### AB-19 Title\n")
    now = datetime.datetime(2026, 11, 5, tzinfo=datetime.UTC)
    with pytest.raises(ValueError, match=r"AB-19\.md"):
        FRAGMENTS.release_changelog_fragments(repository, "2026-11-05", now)
    assert (repository / "changes" / "AB-19.md").exists()


def test_release_refuses_an_empty_changes_directory(repository: Path):
    now = datetime.datetime(2026, 11, 5, tzinfo=datetime.UTC)
    with pytest.raises(ValueError, match="no fragments"):
        FRAGMENTS.release_changelog_fragments(repository, "2026-11-05", now)


def test_preview_command_prints_the_unreleased_entries(repository: Path, capsys):
    write(repository, "changes/AB-19.md", VALID_FRAGMENT)
    assert FRAGMENTS.main(["--repository", str(repository), "preview"]) == 0
    output = capsys.readouterr().out
    assert output.startswith("## Unreleased\n\n### AB-19 Assemble the changelog\n")


STRICT_SETTINGS = MODELS.RepositorySettings(
    issue_id_pattern="AB-[0-9]{2}",
    changes_directory="docs/changes",
    changelog_file="docs/CHANGELOG.md",
)


def test_validate_changelog_fragment_follows_the_issue_id_pattern_setting():
    assert FRAGMENTS.validate_changelog_fragment("AB-19.md", VALID_FRAGMENT, STRICT_SETTINGS) == []
    problems = FRAGMENTS.validate_changelog_fragment(
        "CD-19.md", "### CD-19 Other\n\n- x\n", STRICT_SETTINGS
    )
    assert any("issue-id-pattern: AB-[0-9]{2}" in problem for problem in problems)


def test_find_issue_id_in_branch_name_ignores_case_for_an_uppercase_pattern():
    issue_id = FRAGMENTS.find_issue_id_in_branch_name("ab-19-assemble", STRICT_SETTINGS)
    assert issue_id == "ab-19"


def test_check_and_release_use_the_configured_paths(repository: Path):
    write(repository, "docs/changes/AB-19.md", VALID_FRAGMENT)
    write(repository, "docs/CHANGELOG.md", CHANGELOG_TEXT)
    assert FRAGMENTS.check_changelog_fragments(repository, "ab-19-x", STRICT_SETTINGS) == []
    now = datetime.datetime(2026, 11, 5, tzinfo=datetime.UTC)
    FRAGMENTS.release_changelog_fragments(repository, "2026-11-05", now, STRICT_SETTINGS)
    assert "### AB-19 Assemble the changelog" in (repository / "docs/CHANGELOG.md").read_text()
    assert not (repository / "docs/changes/AB-19.md").exists()


def test_main_reads_the_settings_file(repository: Path, capsys):
    write(repository, "docs/changes/AB-19.md", VALID_FRAGMENT)
    settings_file = write(
        repository,
        "tools/pyproject.toml",
        "[tool.devops-tools]\nissue-id-pattern = 'AB-[0-9]{2}'\n"
        'changes-directory = "docs/changes"\n',
    )
    arguments = ["--repository", str(repository), "--settings-file", str(settings_file)]
    assert FRAGMENTS.main([*arguments, "check", "--branch", "ab-19-x"]) == 0
    assert FRAGMENTS.main([*arguments, "check", "--branch", "cd-19-x"]) == 1
    assert "name does not start with an issue ID" in capsys.readouterr().out


def test_main_reports_a_bad_settings_file(repository: Path, capsys):
    settings_file = write(repository, "pyproject.toml", "[tool.devops-tools]\ntypo = 'x'\n")
    exit_code = FRAGMENTS.main(
        ["--repository", str(repository), "--settings-file", str(settings_file), "check"]
    )
    assert exit_code == 2
    assert "unknown key" in capsys.readouterr().err
