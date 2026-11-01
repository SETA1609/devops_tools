"""
Rebase open branches, keeping both sides' new changelog entries.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from devops_tools import rebase_open_branches as REBASE


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


def commit_all(repository: Path, message: str) -> None:
    git(repository, "add", "-A")
    git(repository, "commit", "-m", message)


def init_repository(tmp: Path) -> Path:
    repository = tmp / "repo"
    repository.mkdir()
    git(repository, "init", "-b", "main")
    git(repository, "config", "user.email", "test@example.com")
    git(repository, "config", "user.name", "Test")
    write(
        repository,
        "CHANGELOG.md",
        "# Changelog\n\n## Unreleased\n\n### Old\n\n- shared\n",
    )
    write(repository, "docs/note.md", "# Note\n\nShared sentence.\n")
    write(repository, "src/app.txt", "value = 1;\n")
    commit_all(repository, "Initial")
    return repository


def point_origin_at(repository: Path, *branches: str) -> None:
    for branch in branches:
        sha = git(repository, "rev-parse", branch).stdout.strip()
        git(repository, "update-ref", f"refs/remotes/origin/{branch}", sha)


def test_pull_request_branch_names_skip_forks_and_other_bases() -> None:
    names = REBASE.pull_request_branch_names(
        [
            {
                "base": {"ref": "main"},
                "head": {"ref": "cd-04-pin-library", "repo": {"full_name": "owner/project"}},
            },
            {
                "base": {"ref": "main"},
                "head": {"ref": "fork-branch", "repo": {"full_name": "other/project"}},
            },
            {
                "base": {"ref": "release"},
                "head": {"ref": "release-fix", "repo": {"full_name": "owner/project"}},
            },
            {
                "base": {"ref": "main"},
                "head": {"ref": "--force", "repo": {"full_name": "owner/project"}},
            },
            {
                "base": {"ref": "main"},
                "head": {"ref": "main", "repo": {"full_name": "owner/project"}},
            },
        ],
        "owner/project",
        "main",
    )
    assert names == ["cd-04-pin-library"]


def test_rebase_keeps_both_changelog_entries_and_the_branch_code(tmp_path: Path) -> None:
    repository = init_repository(tmp_path)
    git(repository, "switch", "-c", "feature")
    write(
        repository,
        "CHANGELOG.md",
        "# Changelog\n\n## Unreleased\n\n### From branch\n\n- branch work\n\n### Old\n\n- shared\n",
    )
    write(repository, "src/app.txt", "value = 1;\nadded = true;\n")
    commit_all(repository, "Feature")
    git(repository, "switch", "main")
    write(
        repository,
        "CHANGELOG.md",
        "# Changelog\n\n## Unreleased\n\n### From main\n\n- main work\n\n### Old\n\n- shared\n",
    )
    commit_all(repository, "Main docs")
    point_origin_at(repository, "main", "feature")
    before = git(repository, "rev-parse", "feature").stdout.strip()

    exit_code = REBASE.main(
        ["--repository", str(repository), "--branches", "feature", "--no-push", "--no-fetch"]
    )

    assert exit_code == 0
    after = git(repository, "rev-parse", "feature").stdout.strip()
    assert after != before
    changelog = git(repository, "show", "feature:CHANGELOG.md").stdout
    app_text = git(repository, "show", "feature:src/app.txt").stdout
    assert "<<<<<<<" not in changelog
    assert changelog.index("### From branch") < changelog.index("### From main")
    assert "branch work" in changelog
    assert "main work" in changelog
    assert "added = true;" in app_text
    assert git(repository, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() == "main"


def test_a_docs_conflict_leaves_the_branch_unmoved(tmp_path: Path) -> None:
    repository = init_repository(tmp_path)
    git(repository, "switch", "-c", "feature")
    write(repository, "docs/note.md", "# Note\n\nShared sentence, branch wording.\n")
    commit_all(repository, "Feature docs")
    git(repository, "switch", "main")
    write(repository, "docs/note.md", "# Note\n\nShared sentence, main wording.\n")
    commit_all(repository, "Main docs")
    point_origin_at(repository, "main", "feature")
    before = git(repository, "rev-parse", "feature").stdout.strip()

    exit_code = REBASE.main(
        ["--repository", str(repository), "--branches", "feature", "--no-push", "--no-fetch"]
    )

    assert exit_code == 1
    assert git(repository, "rev-parse", "feature").stdout.strip() == before
    assert git(repository, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() == "main"


def test_code_conflict_leaves_the_branch_unmoved(tmp_path: Path) -> None:
    repository = init_repository(tmp_path)
    git(repository, "switch", "-c", "feature")
    write(repository, "src/app.txt", "value = 2;\n")
    commit_all(repository, "Feature code")
    git(repository, "switch", "main")
    write(repository, "src/app.txt", "value = 3;\n")
    commit_all(repository, "Main code")
    point_origin_at(repository, "main", "feature")
    before = git(repository, "rev-parse", "feature").stdout.strip()

    exit_code = REBASE.main(
        ["--repository", str(repository), "--branches", "feature", "--no-push", "--no-fetch"]
    )

    assert exit_code == 1
    assert git(repository, "rev-parse", "feature").stdout.strip() == before
    assert "value = 2" in git(repository, "show", "feature:src/app.txt").stdout
    assert git(repository, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() == "main"


def test_one_failure_does_not_stop_the_other_branch(tmp_path: Path) -> None:
    repository = init_repository(tmp_path)
    git(repository, "switch", "-c", "docs-branch")
    write(
        repository,
        "CHANGELOG.md",
        "# Changelog\n\n## Unreleased\n\n### Docs branch\n\n- docs\n\n### Old\n\n- shared\n",
    )
    commit_all(repository, "Docs")
    git(repository, "switch", "main")
    git(repository, "switch", "-c", "code-branch")
    write(repository, "src/app.txt", "value = 4;\n")
    commit_all(repository, "Code")
    git(repository, "switch", "main")
    write(repository, "src/app.txt", "value = 5;\n")
    write(
        repository,
        "CHANGELOG.md",
        "# Changelog\n\n## Unreleased\n\n### On main\n\n- main\n\n### Old\n\n- shared\n",
    )
    commit_all(repository, "Main moves")
    point_origin_at(repository, "main", "docs-branch", "code-branch")
    code_before = git(repository, "rev-parse", "code-branch").stdout.strip()

    exit_code = REBASE.main(
        [
            "--repository",
            str(repository),
            "--branches",
            "docs-branch",
            "code-branch",
            "--no-push",
            "--no-fetch",
        ]
    )

    assert exit_code == 1
    changelog = git(repository, "show", "docs-branch:CHANGELOG.md").stdout
    assert "### Docs branch" in changelog
    assert "### On main" in changelog
    assert changelog.index("### Docs branch") < changelog.index("### On main")
    assert git(repository, "rev-parse", "code-branch").stdout.strip() == code_before


CHANGELOG_BASE = (
    "# Changelog\n\nLast updated: 2026-10-29T10:00Z\n\n## Unreleased\n\n### Old\n\n- old\n"
)
CHANGELOG_TARGET = (
    "# Changelog\n\nLast updated: 2026-10-29T12:00Z\n\n## Unreleased\n\n"
    "### Main\n\n- main\n\n### Old\n\n- old\n"
)
CHANGELOG_BRANCH = (
    "# Changelog\n\nLast updated: 2026-10-29T11:00Z\n\n## Unreleased\n\n"
    "### Feature\n\n- feature\n\n### Old\n\n- old\n"
)
CHANGELOG_BOTH_ENTRIES = (
    "# Changelog\n\nLast updated: 2026-10-29T12:00Z\n\n## Unreleased\n\n"
    "### Feature\n\n- feature\n\n### Main\n\n- main\n\n### Old\n\n- old\n"
)


def test_merge_changelog_sides_takes_the_newer_timestamp_and_both_entries() -> None:
    merged = REBASE.merge_changelog_sides(CHANGELOG_BASE, CHANGELOG_TARGET, CHANGELOG_BRANCH)
    assert merged == CHANGELOG_BOTH_ENTRIES


def test_merge_changelog_sides_takes_the_newer_timestamp_from_the_branch_too() -> None:
    branch_is_newer = CHANGELOG_BRANCH.replace("T11:00Z", "T13:00Z")
    merged = REBASE.merge_changelog_sides(CHANGELOG_BASE, CHANGELOG_TARGET, branch_is_newer)
    assert merged == CHANGELOG_BOTH_ENTRIES.replace("T12:00Z", "T13:00Z")


def test_merge_changelog_sides_refuses_two_edits_of_the_same_entry() -> None:
    target = CHANGELOG_BASE.replace("- old\n", "- old, as main says\n")
    branch = CHANGELOG_BASE.replace("- old\n", "- old, as the branch says\n")
    assert REBASE.merge_changelog_sides(CHANGELOG_BASE, target, branch) is None


def test_merge_changelog_sides_merges_changes_that_do_not_touch() -> None:
    base = CHANGELOG_BASE + "\n### Older\n\n- older\n"
    target = base.replace("- older\n", "- older, fixed on main\n")
    branch = base.replace("### Old\n", "### Feature\n\n- feature\n\n### Old\n")
    merged = REBASE.merge_changelog_sides(base, target, branch)
    assert merged == branch.replace("- older\n", "- older, fixed on main\n")


def test_write_merged_changelog_writes_the_target_file_or_leaves_it(tmp_path: Path) -> None:
    base_path = tmp_path / "base"
    target_path = tmp_path / "target"
    branch_path = tmp_path / "branch"
    base_path.write_text(CHANGELOG_BASE, encoding="utf-8")
    target_path.write_text(CHANGELOG_TARGET, encoding="utf-8")
    branch_path.write_text(CHANGELOG_BRANCH, encoding="utf-8")
    assert REBASE.write_merged_changelog(str(base_path), str(target_path), str(branch_path)) == 0
    assert target_path.read_text(encoding="utf-8") == CHANGELOG_BOTH_ENTRIES

    conflicting_target = CHANGELOG_BASE.replace("- old\n", "- old, as main says\n")
    target_path.write_text(conflicting_target, encoding="utf-8")
    branch_path.write_text(CHANGELOG_BASE.replace("- old\n", "- old, branch\n"), encoding="utf-8")
    assert REBASE.write_merged_changelog(str(base_path), str(target_path), str(branch_path)) == 1
    assert target_path.read_text(encoding="utf-8") == conflicting_target


def test_rebase_merges_a_timestamp_and_top_entry_conflict(tmp_path: Path) -> None:
    repository = init_repository(tmp_path)
    write(repository, "CHANGELOG.md", CHANGELOG_BASE)
    commit_all(repository, "Timestamped changelog")
    git(repository, "switch", "-c", "feature")
    write(repository, "CHANGELOG.md", CHANGELOG_BRANCH)
    commit_all(repository, "Feature entry")
    git(repository, "switch", "main")
    write(repository, "CHANGELOG.md", CHANGELOG_TARGET)
    commit_all(repository, "Main entry")
    point_origin_at(repository, "main", "feature")

    exit_code = REBASE.main(
        ["--repository", str(repository), "--branches", "feature", "--no-push", "--no-fetch"]
    )

    assert exit_code == 0
    assert git(repository, "show", "feature:CHANGELOG.md").stdout == CHANGELOG_BOTH_ENTRIES


def test_rebase_leaves_a_branch_that_edits_the_same_changelog_entry(tmp_path: Path) -> None:
    repository = init_repository(tmp_path)
    git(repository, "switch", "-c", "feature")
    write(repository, "CHANGELOG.md", "# Changelog\n\n## Unreleased\n\n### Old\n\n- branch\n")
    commit_all(repository, "Feature edits Old")
    git(repository, "switch", "main")
    write(repository, "CHANGELOG.md", "# Changelog\n\n## Unreleased\n\n### Old\n\n- main\n")
    commit_all(repository, "Main edits Old")
    point_origin_at(repository, "main", "feature")
    before = git(repository, "rev-parse", "feature").stdout.strip()

    exit_code = REBASE.main(
        ["--repository", str(repository), "--branches", "feature", "--no-push", "--no-fetch"]
    )

    assert exit_code == 1
    assert git(repository, "rev-parse", "feature").stdout.strip() == before


def test_rebase_refuses_a_dirty_working_tree(tmp_path: Path) -> None:
    repository = init_repository(tmp_path)
    git(repository, "switch", "-c", "feature")
    write(repository, "src/app.txt", "value = 1;\nadded = true;\n")
    commit_all(repository, "Feature")
    git(repository, "switch", "main")
    write(repository, "docs/note.md", "# Note\n\nMain moved.\n")
    commit_all(repository, "Main")
    point_origin_at(repository, "main", "feature")
    before = git(repository, "rev-parse", "feature").stdout.strip()
    write(repository, "docs/note.md", "# Note\n\nUncommitted edit.\n")

    exit_code = REBASE.main(
        ["--repository", str(repository), "--branches", "feature", "--no-push", "--no-fetch"]
    )

    assert exit_code == 1
    assert git(repository, "rev-parse", "feature").stdout.strip() == before
    assert (repository / "docs/note.md").read_text(
        encoding="utf-8"
    ) == "# Note\n\nUncommitted edit.\n"


def test_rebase_does_not_move_a_local_branch_with_unpushed_commits(tmp_path: Path) -> None:
    repository = init_repository(tmp_path)
    git(repository, "switch", "-c", "feature")
    write(repository, "src/pushed.txt", "pushed = true;\n")
    commit_all(repository, "Pushed")
    point_origin_at(repository, "feature")
    write(repository, "src/local.txt", "local = true;\n")
    commit_all(repository, "Local only")
    local_tip = git(repository, "rev-parse", "feature").stdout.strip()
    git(repository, "switch", "main")
    write(repository, "docs/note.md", "# Note\n\nMain moved.\n")
    commit_all(repository, "Main")
    point_origin_at(repository, "main")

    exit_code = REBASE.main(
        ["--repository", str(repository), "--branches", "feature", "--no-push", "--no-fetch"]
    )

    assert exit_code == 0
    assert git(repository, "rev-parse", "feature").stdout.strip() == local_tip


def test_local_branch_can_follow_remote(tmp_path: Path) -> None:
    repository = init_repository(tmp_path)
    tip = git(repository, "rev-parse", "main").stdout.strip()
    assert REBASE.local_branch_can_follow_remote(str(repository), "missing-branch", tip)
    assert REBASE.local_branch_can_follow_remote(str(repository), "main", tip)
    write(repository, "src/local.txt", "local = true;\n")
    commit_all(repository, "Local only")
    assert not REBASE.local_branch_can_follow_remote(str(repository), "main", tip)


def test_working_tree_is_clean_ignores_untracked_files(tmp_path: Path) -> None:
    repository = init_repository(tmp_path)
    assert REBASE.working_tree_is_clean(str(repository))
    write(repository, "untracked.txt", "scratch\n")
    assert REBASE.working_tree_is_clean(str(repository))
    write(repository, "src/app.txt", "value = 9;\n")
    assert not REBASE.working_tree_is_clean(str(repository))
    git(repository, "add", "src/app.txt")
    assert not REBASE.working_tree_is_clean(str(repository))


def test_branch_name_rejects_refspec_tricks() -> None:
    assert REBASE.branch_name_is_safe("ab-14-split-the-tool")
    assert not REBASE.branch_name_is_safe("--force")
    assert not REBASE.branch_name_is_safe("feature..main")
    assert not REBASE.branch_name_is_safe("refs/heads/main")


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (None, None),
        ('<https://example.test/pulls?page=2>; rel="next"', "https://example.test/pulls?page=2"),
        ('<https://example.test/pulls?page=1>; rel="prev"', None),
    ],
)
def test_next_link(header: str | None, expected: str | None) -> None:
    assert REBASE.next_link(header) == expected


def test_rebase_reads_the_target_and_changelog_file_from_the_settings(tmp_path: Path) -> None:
    repository = init_repository(tmp_path)
    git(repository, "branch", "-m", "main", "trunk")
    write(
        repository,
        "pyproject.toml",
        '[tool.devops-tools]\nmain-branch = "trunk"\nchangelog-file = "docs/HISTORY.md"\n',
    )
    write(repository, "docs/HISTORY.md", "# History\n\n### Old\n\n- shared\n")
    commit_all(repository, "Settings")
    git(repository, "switch", "-c", "feature")
    write(
        repository,
        "docs/HISTORY.md",
        "# History\n\n### From branch\n\n- b\n\n### Old\n\n- shared\n",
    )
    commit_all(repository, "Feature")
    git(repository, "switch", "trunk")
    write(
        repository, "docs/HISTORY.md", "# History\n\n### From trunk\n\n- t\n\n### Old\n\n- shared\n"
    )
    commit_all(repository, "Trunk docs")
    point_origin_at(repository, "trunk", "feature")

    exit_code = REBASE.main(
        ["--repository", str(repository), "--branches", "feature", "--no-push", "--no-fetch"]
    )

    assert exit_code == 0
    history = git(repository, "show", "feature:docs/HISTORY.md").stdout
    assert history.index("### From branch") < history.index("### From trunk")
    assert (
        git(repository, "merge-base", "--is-ancestor", "trunk", "feature", check=False).returncode
        == 0
    )
    attributes = (repository / ".git" / "info" / "attributes").read_text()
    assert "changelog-entries" not in attributes


def test_rebase_reports_a_bad_settings_file(tmp_path: Path, capsys) -> None:
    repository = init_repository(tmp_path)
    write(repository, "pyproject.toml", "[tool.devops-tools]\nmain = 'x'\n")
    exit_code = REBASE.main(["--repository", str(repository), "--branches", "x", "--no-fetch"])
    assert exit_code == 2
    assert "unknown key" in capsys.readouterr().err
