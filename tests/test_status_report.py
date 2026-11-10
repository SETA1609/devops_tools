"""
Offline status report tests against a local origin repository.
"""

import json
import pathlib
import subprocess

import pytest

from devops_tools import status_report

FOUNDATIONS_STORY = """# Foundations

## AB Repo

#### AB-01 Merged thing
- Status: review
- Do: merged already.

#### AB-02 Open thing
- Status: review

#### AB-03 Behind thing
- Status: doing

#### AB-04 Local thing
- Status: todo

#### AB-05 Later thing
- Status: todo
"""
STACK_STORY = """# Stack

#### CD-04 Done thing
- Status: done

#### CD-05 Copy helpers
- Status: todo
"""
IGNORED_STORY = """# Ignored

#### X0-01 Not a story file
- Status: doing
"""


def git(repository: pathlib.Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repository), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def commit_file(repository: pathlib.Path, relative: str, text: str, message: str) -> str:
    path = repository / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    git(repository, "add", "-A")
    git(repository, "commit", "-q", "-m", message)
    return git(repository, "rev-parse", "HEAD")


@pytest.fixture
def workspace(tmp_path: pathlib.Path) -> dict[str, pathlib.Path]:
    """
    A clone of a local origin with: ab-01-merged (squash-merged as #1, remote deleted, main
    later edits the same file), ab-02-open (pushed, ahead, in a worktree with an uncommitted
    change, pull request #2), ab-03-behind (pushed before the merge, ahead and behind), and
    ab-04-local (never pushed).
    """
    origin = tmp_path / "origin.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    repository = tmp_path / "work"
    git(tmp_path, "clone", "-q", str(origin), str(repository))
    git(repository, "config", "user.email", "test@example.com")
    git(repository, "config", "user.name", "Test")
    git(repository, "checkout", "-q", "-b", "main")
    commit_file(repository, "docs/stories/02-foundations.md", FOUNDATIONS_STORY, "Stories")
    commit_file(repository, "docs/stories/01-stack.md", STACK_STORY, "Stack")
    commit_file(repository, "docs/stories/README.md", IGNORED_STORY, "Readme")
    commit_file(repository, "docs/stories/done.md", IGNORED_STORY, "Done")
    git(repository, "push", "-q", "-u", "origin", "main")

    git(repository, "switch", "-q", "-c", "ab-03-behind")
    commit_file(repository, "behind.txt", "behind\n", "AB-03: Behind")
    git(repository, "push", "-q", "-u", "origin", "ab-03-behind")

    git(repository, "switch", "-q", "-c", "ab-01-merged", "main")
    commit_file(repository, "notes/one.txt", "first line\nsecond line\n", "AB-01: One")
    merged_branch_head = commit_file(repository, "notes/two.txt", "two\n", "AB-01: Two")
    git(repository, "push", "-q", "-u", "origin", "ab-01-merged")
    git(repository, "switch", "-q", "main")
    git(repository, "merge", "-q", "--squash", "ab-01-merged")
    git(repository, "commit", "-q", "-m", "AB 01 merged thing (#1)")
    commit_file(repository, "notes/one.txt", "first line\nchanged later\n", "Later edit (#3)")
    git(repository, "push", "-q", "origin", "main")
    git(repository, "push", "-q", "origin", "--delete", "ab-01-merged")
    git(origin, "update-ref", "refs/pull/1/head", merged_branch_head)

    git(repository, "switch", "-q", "-c", "ab-02-open", "main")
    open_branch_head = commit_file(repository, "open.txt", "open\n", "AB-02: Open")
    git(repository, "push", "-q", "-u", "origin", "ab-02-open")
    git(origin, "update-ref", "refs/pull/2/head", open_branch_head)

    git(repository, "switch", "-q", "-c", "ab-04-local", "main")
    commit_file(repository, "local.txt", "local\n", "AB-04: Local")
    git(repository, "switch", "-q", "main")

    worktree = tmp_path / "worktree-ab-02"
    git(repository, "worktree", "add", "-q", str(worktree), "ab-02-open")
    (worktree / "open.txt").write_text("edited\n", encoding="utf-8")
    git(repository, "fetch", "-q", "--prune", "origin")
    return {"origin": origin, "repository": repository, "worktree": worktree}


def branch_by_name(statuses) -> dict:
    return {status.name: status for status in statuses}


# Branches


def test_branches_are_compared_with_main(workspace):
    """
    What: list_local_branch_statuses.
    When: local branches are merged and deleted, pushed and ahead, pushed before a merge, and never
    pushed.
    Then: each gets its upstream state, its ahead and behind counts, and whether main has its
    content.
    """
    statuses = status_report.list_local_branch_statuses(workspace["repository"], "origin/main")
    branches = branch_by_name(statuses)
    assert sorted(branches) == ["ab-01-merged", "ab-02-open", "ab-03-behind", "ab-04-local"]
    assert branches["ab-01-merged"].upstream_state == "gone"
    assert branches["ab-01-merged"].is_content_in_main
    assert branches["ab-02-open"].upstream_state == "tracking"
    assert branches["ab-02-open"].commits_ahead_of_main == 1
    assert branches["ab-02-open"].commits_behind_main == 0
    assert not branches["ab-02-open"].is_content_in_main
    assert branches["ab-03-behind"].commits_ahead_of_main == 1
    assert branches["ab-03-behind"].commits_behind_main == 2
    assert branches["ab-04-local"].upstream_state == "none"


def test_branch_merged_after_a_later_rebase_is_found_by_its_issue_id(workspace):
    """
    What: list_local_branch_statuses.
    When: a stale local copy of a branch that was rebased and then squash-merged as #4.
    Then: its content does not match main, but the issue ID in the main subject gives merged in #4.
    """
    repository = workspace["repository"]
    # A local copy left behind when the remote branch was rebased and then squash-merged:
    # neither its tree, its patch, nor its files match main any more.
    git(repository, "switch", "-q", "-c", "ab-03-merged-elsewhere", "origin/main~3")
    commit_file(repository, "notes/one.txt", "first line\nstale copy\n", "AB-03: Stale")
    git(repository, "switch", "-q", "main")
    commit_file(repository, "notes/three.txt", "three\n", "AB 03 behind thing (#4)")
    statuses = status_report.list_local_branch_statuses(repository, "main")
    stale_copy = branch_by_name(statuses)["ab-03-merged-elsewhere"]
    assert not stale_copy.is_content_in_main
    assert stale_copy.merged_pull_request_number == 4
    assert branch_by_name(statuses)["ab-02-open"].merged_pull_request_number is None


@pytest.mark.parametrize(
    ("branch_name", "issue_id"),
    [
        ("ab-14-split-the-tool", "ab-14"),
        ("agent/claude/cd-04-pin-library", "cd-04"),
        ("ab1.1-02-read-the-header", "ab1.1-02"),
        ("ab3b-01-sim-and-world", "ab3b-01"),
        ("main", None),
        ("release/1", None),
    ],
)
def test_issue_id_is_read_from_the_branch_name(branch_name, issue_id):
    """
    What: find_issue_id_in_branch_name.
    When: branch names with and without an issue ID, with an agent prefix, a dotted story, or a
    letter suffix.
    Then: the issue ID is returned, or None for branches like main and release/1.
    """
    assert status_report.find_issue_id_in_branch_name(branch_name) == issue_id


def test_report_suggests_deleting_a_branch_merged_by_issue_id(workspace):
    """
    What: build_status_report.
    When: a branch's remote is gone and main names its issue with (#4), but its content differs.
    Then: the suggested actions say it was merged in #4 and how to delete it.
    """
    repository = workspace["repository"]
    git(repository, "switch", "-q", "main")
    # The remote branch was rebased and changed before its squash merge, so the local copy's
    # content does not match main; only the issue ID in the subject links them.
    commit_file(repository, "behind.txt", "behind, as rebased\n", "AB 03 behind thing (#4)")
    git(repository, "push", "-q", "origin", "main")
    git(repository, "push", "-q", "origin", "--delete", "ab-03-behind")
    report = status_report.build_status_report(
        repository, "main", should_fetch=True, gh_executable=None
    )
    actions = "\n".join(report.suggested_actions)
    assert "ab-03-behind was merged in #4" in actions
    assert "git branch -D ab-03-behind" in actions


def test_worktree_and_its_uncommitted_changes_are_reported(workspace):
    """
    What: list_local_branch_statuses.
    When: a branch is checked out in a worktree with one uncommitted change.
    Then: the branch lists that worktree path and one uncommitted change; other branches list none.
    """
    statuses = status_report.list_local_branch_statuses(workspace["repository"], "origin/main")
    open_branch = branch_by_name(statuses)["ab-02-open"]
    assert pathlib.Path(open_branch.worktree_path).resolve() == workspace["worktree"].resolve()
    assert open_branch.worktree_uncommitted_change_count == 1
    assert branch_by_name(statuses)["ab-04-local"].worktree_path is None


def test_squash_merge_counts_even_after_main_edits_the_same_file(workspace):
    """
    What: is_branch_content_in_main.
    When: a branch was squash-merged and main later edited a file the branch changed.
    Then: the branch still counts as in main.
    """
    assert status_report.is_branch_content_in_main(
        workspace["repository"], "ab-01-merged", "origin/main"
    )


def test_ancestor_of_main_is_in_main(workspace):
    """
    What: is_branch_content_in_main.
    When: a branch points at an older main commit.
    Then: it counts as in main.
    """
    repository = workspace["repository"]
    git(repository, "branch", "old-main", "origin/main~1")
    assert status_report.is_branch_content_in_main(repository, "old-main", "origin/main")


def test_unmerged_branch_is_not_in_main(workspace):
    """
    What: is_branch_content_in_main.
    When: a branch has a commit main does not have.
    Then: it does not count as in main.
    """
    assert not status_report.is_branch_content_in_main(
        workspace["repository"], "ab-03-behind", "origin/main"
    )


def test_worktree_paths_are_listed_by_branch(workspace):
    """
    What: list_worktree_paths_by_branch.
    When: the main checkout and one linked worktree exist.
    Then: each branch maps to the path of the worktree that has it checked out.
    """
    paths = status_report.list_worktree_paths_by_branch(workspace["repository"])
    assert pathlib.Path(paths["ab-02-open"]).resolve() == workspace["worktree"].resolve()
    assert pathlib.Path(paths["main"]).resolve() == workspace["repository"].resolve()


# Pull requests


def test_pull_request_refs_are_open_when_their_head_is_a_branch_tip(workspace):
    """
    What: list_pull_request_statuses without gh.
    When: one pull request ref still points at a branch tip and one at a deleted branch.
    Then: only the first is reported, from refs.
    """
    pull_requests = status_report.list_pull_request_statuses(workspace["repository"], None)
    assert [(pull.number, pull.branch, pull.source) for pull in pull_requests] == [
        (2, "ab-02-open", "refs")
    ]


def test_failing_gh_falls_back_to_refs(workspace, tmp_path):
    """
    What: list_pull_request_statuses.
    When: gh exists but exits with an error.
    Then: the pull requests come from refs instead.
    """
    failing_gh = tmp_path / "gh"
    failing_gh.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    failing_gh.chmod(0o755)
    pull_requests = status_report.list_pull_request_statuses(
        workspace["repository"], str(failing_gh)
    )
    assert [pull.number for pull in pull_requests] == [2]


def test_gh_output_is_used_when_gh_works(workspace, tmp_path):
    """
    What: list_pull_request_statuses.
    When: gh prints a JSON list of open pull requests.
    Then: that list is used, marked as from gh.
    """
    fake_gh = tmp_path / "gh"
    listing = json.dumps([{"number": 7, "headRefName": "ab-02-open", "headRefOid": "abc"}])
    fake_gh.write_text(f"#!/bin/sh\necho '{listing}'\n", encoding="utf-8")
    fake_gh.chmod(0o755)
    pull_requests = status_report.list_pull_request_statuses(workspace["repository"], str(fake_gh))
    assert [(pull.number, pull.branch, pull.source) for pull in pull_requests] == [
        (7, "ab-02-open", "gh")
    ]


# Submodules


@pytest.mark.parametrize(
    ("line", "state"),
    [
        (" 01223bd645eb8a0aa73b539fe5b469a8f1cf44a2 libs/library (heads/main)", "ok"),
        ("+4f67f5bbc82e1584141233a952eb5f74f40edfaf libs/library (4f67f5b)", "not_at_pin"),
        ("-01223bd645eb8a0aa73b539fe5b469a8f1cf44a2 libs/library", "not_initialized"),
        ("U01223bd645eb8a0aa73b539fe5b469a8f1cf44a2 libs/library", "conflict"),
    ],
)
def test_submodule_status_lines_are_parsed(line: str, state: str):
    """
    What: parse_submodule_status_line.
    When: a `git submodule status` line starts with a space, +, -, or U.
    Then: the state is ok, not_at_pin, not_initialized, or conflict, with the path and full commit.
    """
    status = status_report.parse_submodule_status_line(line)
    assert status is not None
    assert status.path == "libs/library"
    assert status.state == state
    assert len(status.pinned_or_checked_out_commit) == 40


def test_blank_submodule_status_line_is_skipped():
    """
    What: parse_submodule_status_line.
    When: the line is empty.
    Then: it returns None.
    """
    assert status_report.parse_submodule_status_line("") is None


# Story issues


@pytest.mark.parametrize(
    ("issue_id", "subjects", "number"),
    [
        ("AB-14", ["AB 14 split the tool into commands (#20)"], 20),
        ("CD-04", ["CD-04: Pin the library as a dependency (#11)"], 11),
        ("AB1.1-02", ["AB1.1 02 read the header (#30)"], 30),
        ("AB-14", ["AB-14: Write down the executables"], None),
        ("AB-1", ["AB-14: Something (#20)"], None),
        ("AB-14", ["Mention AB-14 in passing (#9)"], None),
    ],
)
def test_merged_pull_request_number_is_found_in_main_subjects(issue_id, subjects, number):
    """
    What: find_merged_pull_request_number.
    When: main subjects name the issue with a dash or a space and `(#N)`, or lack one of those, or
    name a longer ID.
    Then: only a subject that starts with the issue ID and ends with `(#N)` gives N.
    """
    assert status_report.find_merged_pull_request_number(issue_id, subjects) == number


def test_active_issues_come_first_then_the_first_todo_per_file(workspace):
    """
    What: list_story_issue_statuses.
    When: story files hold doing, review, todo, and done issues, plus README.md and done.md.
    Then: doing and review issues come first, then the first todo of each story file; README.md and
    done.md are skipped.
    """
    issues = status_report.list_story_issue_statuses(
        workspace["repository"] / "docs" / "stories",
        ["AB 01 merged thing (#1)", "Later edit (#3)"],
    )
    assert [(issue.issue_id, issue.status) for issue in issues] == [
        ("AB-01", "review"),
        ("AB-02", "review"),
        ("AB-03", "doing"),
        ("CD-05", "todo"),
        ("AB-04", "todo"),
    ]
    assert issues[0].merged_pull_request_number == 1
    assert issues[1].merged_pull_request_number is None
    assert issues[0].story_file == "02-foundations.md"


# Whole report


def test_report_suggests_actions_without_changing_anything(workspace):
    """
    What: build_status_report.
    When: it runs with a fetch on a checkout with merged, behind, and worktree branches.
    Then: no ref changes, and the suggested actions name the merged branch, the done.md move, the
    behind branch, and the dirty worktree.
    """
    repository = workspace["repository"]
    branches_before = git(repository, "for-each-ref", "refs/heads", "refs/remotes")
    report = status_report.build_status_report(
        repository, "main", should_fetch=True, gh_executable=None
    )
    assert git(repository, "for-each-ref", "refs/heads", "refs/remotes") == branches_before
    assert report.current_branch == "main"
    assert report.main_commit_subject == "Later edit (#3)"
    actions = "\n".join(report.suggested_actions)
    assert "ab-01-merged" in actions
    assert "AB-01" in actions and "done.md" in actions
    assert "ab-03-behind" in actions
    assert "worktree-ab-02" in actions
    assert "ab-02-open" not in actions.replace("worktree-ab-02", "")


def test_text_report_names_every_section(workspace):
    """
    What: render_status_report_text.
    When: the report has branches, a pull request, and story issues.
    Then: the text names each of them and ends with suggested actions.
    """
    report = status_report.build_status_report(
        workspace["repository"], "main", should_fetch=False, gh_executable=None
    )
    text = status_report.render_status_report_text(report)
    for expected in ["ab-02-open", "#2", "AB-03", "CD-05", "Suggested actions"]:
        assert expected in text


def test_main_prints_json(workspace, capsys):
    """
    What: the status-report command with --json.
    When: it runs without a fetch.
    Then: it exits 0 and prints the report as JSON with the current branch and the local branches.
    """
    exit_code = status_report.main(
        ["--repository", str(workspace["repository"]), "--no-fetch", "--json"]
    )
    assert exit_code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["current_branch"] == "main"
    assert {branch["name"] for branch in report["branches"]} >= {"ab-01-merged", "ab-02-open"}


def test_open_issue_files_list_active_issues_and_the_first_todo_of_each_story(tmp_path):
    """
    What: list_story_issue_statuses with an issues directory.
    When: open per-issue files hold review and todo issues of two stories, numbered past nine.
    Then: review comes first, then the lowest-numbered todo per story in story file order.
    """
    stories_directory = tmp_path / "stories"
    stories_directory.mkdir()
    (stories_directory / "01-first.md").write_text(
        "## CD Later letter, first story\n\n## AB Second story\n", encoding="utf-8"
    )
    open_directory = tmp_path / "issues" / "open"
    open_directory.mkdir(parents=True)
    for issue_id, status in [
        ("AB-10", "todo"),
        ("AB-02", "todo"),
        ("CD-01", "review"),
        ("CD-02", "todo"),
    ]:
        (open_directory / f"{issue_id}.md").write_text(
            f"#### {issue_id} Title\n- Status: {status}\n", encoding="utf-8"
        )
    issues = status_report.list_story_issue_statuses(
        stories_directory, [], issues_directory=tmp_path / "issues"
    )
    assert [(issue.issue_id, issue.story_file) for issue in issues] == [
        ("CD-01", "open/CD-01.md"),
        ("CD-02", "open/CD-02.md"),
        ("AB-02", "open/AB-02.md"),
    ]
