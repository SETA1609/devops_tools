"""
Report where the work stands: branches, worktrees, pull requests, submodules, and story issues.
Reads git and the story files and prints one report with suggested actions. It never changes a
branch, a worktree, or a remote; the only write is `git fetch --prune origin`, skipped with
--no-fetch.
    devops-tools status-report [--repository PATH] [--settings-file PATH] [--main-branch B]
        [--no-fetch] [--json]
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from devops_tools.changelog_fragments import compile_fragment_patterns
from devops_tools.check_submodule_pins import check_submodule_pins
from devops_tools.constants import (
    ACTIVE_ISSUE_STATUSES,
    EXIT_CODE_USAGE_ERROR,
    GIT_TIMEOUT_SECONDS,
    ISSUE_HEADING_LINE,
    ISSUE_STATUS_LINE,
    OPEN_ISSUES_DIRECTORY_NAME,
    STATUS_ON_BRANCH,
    STORY_FILES_SKIPPED,
)
from devops_tools.container import find_repository_root
from devops_tools.exceptions import RepositorySettingsError
from devops_tools.models import (
    BranchStatus,
    PullRequestStatus,
    RepositorySettings,
    StatusReport,
    StoryIssueStatus,
    SubmoduleStatus,
)
from devops_tools.roadmap_order import (
    find_issues_directory,
    find_story_id_of_issue,
    read_roadmap_issues,
)
from devops_tools.settings import read_repository_settings

DEFAULT_REPOSITORY_SETTINGS = RepositorySettings()


def run_git(repository: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return run_command(["git", "-C", str(repository), *args])


def run_command(
    command: list[str], input_text: str | None = None, working_directory: Path | None = None
) -> subprocess.CompletedProcess[str]:
    # English, untranslated git output, so it parses the same on every machine.
    environment = {**os.environ, "LC_ALL": "C"}
    return subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        input=input_text,
        cwd=working_directory,
        env=environment,
        timeout=GIT_TIMEOUT_SECONDS,
    )


def git_output(repository: Path, *args: str) -> str:
    completed = run_git(repository, *args)
    return completed.stdout.strip() if completed.returncode == 0 else ""


def count_uncommitted_changes(checkout: Path) -> int:
    completed = run_git(checkout, "status", "--porcelain", "--untracked-files=no")
    return len(completed.stdout.splitlines()) if completed.returncode == 0 else 0


def compute_patch_ids(repository: Path, patch_text: str) -> set[str]:
    completed = run_command(["git", "-C", str(repository), "patch-id", "--stable"], patch_text)
    return {line.split()[0] for line in completed.stdout.splitlines() if line.strip()}


def is_branch_content_in_main(repository: Path, branch: str, main_reference: str) -> bool:
    """
    True when main already has the branch's changes: it is an ancestor of main, a commit on
    main has its tree or its combined patch (a squash merge), or every file the branch changed
    is identical in main.
    """
    if run_git(repository, "merge-base", "--is-ancestor", branch, main_reference).returncode == 0:
        return True
    merge_base = git_output(repository, "merge-base", branch, main_reference)
    if not merge_base:
        return False
    main_range = f"{merge_base}..{main_reference}"
    branch_tree = git_output(repository, "rev-parse", f"{branch}^{{tree}}")
    if branch_tree in git_output(repository, "log", "--format=%T", main_range).splitlines():
        return True
    branch_patch = run_git(repository, "diff", merge_base, branch).stdout
    branch_patch_ids = compute_patch_ids(repository, branch_patch)
    main_patches = run_git(repository, "log", "-p", "--pretty=format:commit %H", main_range).stdout
    if branch_patch_ids and branch_patch_ids <= compute_patch_ids(repository, main_patches):
        return True
    changed_paths = git_output(repository, "diff", "--name-only", merge_base, branch).splitlines()
    if not changed_paths:
        return False
    for path in changed_paths:
        branch_blob = run_git(repository, "rev-parse", "--verify", "--quiet", f"{branch}:{path}")
        main_blob = run_git(
            repository, "rev-parse", "--verify", "--quiet", f"{main_reference}:{path}"
        )
        if branch_blob.stdout.strip() != main_blob.stdout.strip():
            return False
    return True


def find_issue_id_in_branch_name(
    branch_name: str, issue_id_pattern: str = DEFAULT_REPOSITORY_SETTINGS.issue_id_pattern
) -> str | None:
    """
    `ab-14-split-the-tool` → `ab-14`; `agent/claude/cd-04-pin` → `cd-04`; else None.
    """
    branch_match = compile_fragment_patterns(issue_id_pattern).branch_issue_id.match(branch_name)
    return branch_match.group("issue_id") if branch_match else None


def list_worktree_paths_by_branch(repository: Path) -> dict[str, str]:
    """
    Branch name → worktree path, from `git worktree list --porcelain`.
    """
    paths_by_branch: dict[str, str] = {}
    worktree_path = ""
    for line in git_output(repository, "worktree", "list", "--porcelain").splitlines():
        if line.startswith("worktree "):
            worktree_path = line.removeprefix("worktree ")
        elif line.startswith("branch refs/heads/"):
            paths_by_branch[line.removeprefix("branch refs/heads/")] = worktree_path
    return paths_by_branch


def list_local_branch_statuses(
    repository: Path,
    main_reference: str,
    issue_id_pattern: str = DEFAULT_REPOSITORY_SETTINGS.issue_id_pattern,
) -> list[BranchStatus]:
    """
    Every local branch except the main branch itself, sorted by name.
    """
    main_branch = main_reference.removeprefix("origin/")
    current_branch = git_output(repository, "branch", "--show-current")
    worktree_paths = list_worktree_paths_by_branch(repository)
    main_commit_subjects = git_output(repository, "log", "--format=%s", main_reference).splitlines()
    listing = git_output(
        repository, "for-each-ref", "--format=%(refname:short)%00%(upstream)", "refs/heads"
    )
    statuses: list[BranchStatus] = []
    for line in sorted(listing.splitlines()):
        name, _, upstream = line.partition("\0")
        if name == main_branch:
            continue
        if not upstream:
            upstream_state = "none"
        elif run_git(repository, "rev-parse", "--verify", "--quiet", upstream).returncode == 0:
            upstream_state = "tracking"
        else:
            upstream_state = "gone"
        counts = git_output(
            repository, "rev-list", "--left-right", "--count", f"{name}...{main_reference}"
        ).split()
        ahead, behind = (int(counts[0]), int(counts[1])) if len(counts) == 2 else (0, 0)
        worktree_path = worktree_paths.get(name)
        issue_id = find_issue_id_in_branch_name(name, issue_id_pattern)
        statuses.append(
            BranchStatus(
                name=name,
                upstream_state=upstream_state,
                commits_ahead_of_main=ahead,
                commits_behind_main=behind,
                is_content_in_main=is_branch_content_in_main(repository, name, main_reference),
                merged_pull_request_number=(
                    find_merged_pull_request_number(issue_id, main_commit_subjects)
                    if issue_id
                    else None
                ),
                is_current=name == current_branch,
                worktree_path=worktree_path,
                worktree_uncommitted_change_count=(
                    count_uncommitted_changes(Path(worktree_path)) if worktree_path else 0
                ),
            )
        )
    return statuses


def list_pull_request_statuses(
    repository: Path, gh_executable: str | None
) -> list[PullRequestStatus]:
    """
    Open pull requests from `gh pr list` when gh works, else from refs/pull/*/head on origin.
    """
    if gh_executable:
        try:
            completed = run_command(
                [
                    gh_executable,
                    "pr",
                    "list",
                    "--state",
                    "open",
                    "--json",
                    "number,headRefName,headRefOid",
                ],
                working_directory=repository,
            )
            if completed.returncode == 0:
                return sorted(
                    (
                        PullRequestStatus(
                            number=int(entry["number"]),
                            branch=entry["headRefName"],
                            head_commit=entry["headRefOid"],
                            source="gh",
                        )
                        for entry in json.loads(completed.stdout)
                    ),
                    key=lambda pull_request: pull_request.number,
                )
        except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired):
            pass
    branch_by_tip: dict[str, str] = {}
    head_by_number: dict[int, str] = {}
    for line in git_output(repository, "ls-remote", "origin").splitlines():
        commit_sha, _, reference = line.partition("\t")
        if reference.startswith("refs/heads/"):
            branch_by_tip[commit_sha] = reference.removeprefix("refs/heads/")
        pull_match = re.fullmatch(r"refs/pull/(\d+)/head", reference)
        if pull_match:
            head_by_number[int(pull_match.group(1))] = commit_sha
    return [
        PullRequestStatus(
            number=number, branch=branch_by_tip[head], head_commit=head, source="refs"
        )
        for number, head in sorted(head_by_number.items())
        if head in branch_by_tip
    ]


def parse_submodule_status_line(line: str) -> SubmoduleStatus | None:
    """
    `+<sha> libs/library (desc)` → not_at_pin; `-` → not_initialized; `U` → conflict.
    """
    if len(line) < 42:
        return None
    state_by_prefix = {" ": "ok", "+": "not_at_pin", "-": "not_initialized", "U": "conflict"}
    state = state_by_prefix.get(line[0])
    path_and_description = line[41:].split()
    if state is None or not path_and_description:
        return None
    return SubmoduleStatus(
        path=path_and_description[0],
        pinned_or_checked_out_commit=line[1:41],
        state=state,
    )


def find_merged_pull_request_number(issue_id: str, main_commit_subjects: list[str]) -> int | None:
    """
    The pull request number of a main commit whose subject starts with the issue ID, with a
    dash or a space as separator (`AB-14: …` or `AB 14 …`), and ends with `(#N)`.
    """
    story_id, _, issue_number = issue_id.rpartition("-")
    if not story_id:
        return None
    subject_pattern = re.compile(
        rf"^{re.escape(story_id)}[- ]{re.escape(issue_number)}\b.*\(#(?P<number>\d+)\)\s*$",
        re.IGNORECASE,
    )
    for subject in main_commit_subjects:
        subject_match = subject_pattern.match(subject)
        if subject_match:
            return int(subject_match.group("number"))
    return None


def read_issue_headings_and_statuses(issue_path: Path) -> list[tuple[str, str, str]]:
    """
    (issue ID, title, status) of each issue in a story file or per-issue file, in file order.
    """
    issues: list[tuple[str, str, str]] = []
    heading: tuple[str, str] | None = None
    for line in issue_path.read_text(encoding="utf-8").splitlines():
        heading_match = ISSUE_HEADING_LINE.match(line)
        if heading_match:
            heading = (heading_match.group("issue_id"), heading_match.group("title"))
            continue
        status_match = ISSUE_STATUS_LINE.match(line)
        if status_match and heading is not None:
            issues.append((*heading, status_match.group("status")))
            heading = None
    return issues


def group_open_issue_files_by_story(
    stories_directory: Path, issues_directory: Path
) -> list[list[tuple[str, str, str, str]]]:
    """
    The open per-issue files as (issue ID, title, status, file label), grouped by story: stories
    in story file order, then any others by ID; issues by number within a story.
    """
    _, story_ids_in_order = read_roadmap_issues(stories_directory)
    issues_by_story: dict[str, list[tuple[str, str, str, str]]] = {}
    for issue_file in (issues_directory / OPEN_ISSUES_DIRECTORY_NAME).glob("*.md"):
        label = f"{OPEN_ISSUES_DIRECTORY_NAME}/{issue_file.name}"
        for issue in read_issue_headings_and_statuses(issue_file):
            issues_by_story.setdefault(find_story_id_of_issue(issue[0]), []).append((*issue, label))

    def order_story(story_id: str) -> tuple[int, str]:
        if story_id in story_ids_in_order:
            return (story_ids_in_order.index(story_id), "")
        return (len(story_ids_in_order), story_id)

    return [
        sorted(issues_by_story[story_id], key=lambda issue: int(issue[0].rsplit("-", 1)[1]))
        for story_id in sorted(issues_by_story, key=order_story)
    ]


def list_story_issue_statuses(
    stories_directory: Path,
    main_commit_subjects: list[str],
    issues_directory: Path | None = None,
) -> list[StoryIssueStatus]:
    """
    Issues in doing or review, then the first todo issue of each story file (and, with
    `issues_directory`, of each story among the open per-issue files), in order.
    """
    active_issues: list[StoryIssueStatus] = []
    next_todo_issues: list[StoryIssueStatus] = []
    story_paths = sorted(
        path for path in stories_directory.glob("*.md") if path.name not in STORY_FILES_SKIPPED
    )
    issue_groups = [
        [(*issue, story_path.name) for issue in read_issue_headings_and_statuses(story_path)]
        for story_path in story_paths
    ]
    if issues_directory is not None:
        issue_groups += group_open_issue_files_by_story(stories_directory, issues_directory)
    for issue_group in issue_groups:
        has_next_todo = False
        for issue_id, title, status, file_label in issue_group:
            issue = StoryIssueStatus(
                issue_id=issue_id,
                title=title,
                status=status,
                story_file=file_label,
                merged_pull_request_number=find_merged_pull_request_number(
                    issue_id, main_commit_subjects
                ),
            )
            if status in ACTIVE_ISSUE_STATUSES:
                active_issues.append(issue)
            elif status == "todo" and not has_next_todo:
                next_todo_issues.append(issue)
                has_next_todo = True
    return active_issues + next_todo_issues


def build_suggested_actions(report: StatusReport) -> list[str]:
    """
    One line per thing worth doing, derived from the report; nothing is run.
    """
    actions: list[str] = []
    if report.uncommitted_change_count:
        actions.append(
            f"The checkout on {report.current_branch} has {report.uncommitted_change_count} "
            "uncommitted change(s)."
        )
    merged_branch_names = {
        branch.name
        for branch in report.branches
        if branch.is_content_in_main or branch.merged_pull_request_number
    }
    for branch in report.branches:
        if branch.name in merged_branch_names:
            steps = []
            if branch.worktree_path and not branch.is_current:
                steps.append(f"git worktree remove {branch.worktree_path}")
            if branch.upstream_state == "tracking":
                steps.append(f"git push origin --delete {branch.name}")
            steps.append(f"git branch -D {branch.name}")
            how_merged = (
                f"is already in {report.main_reference}"
                if branch.is_content_in_main
                else f"was merged in #{branch.merged_pull_request_number}"
            )
            actions.append(f"{branch.name} {how_merged}; delete it: " + " && ".join(steps))
            continue
        if branch.upstream_state == "tracking" and branch.commits_behind_main:
            actions.append(
                f"{branch.name} is {branch.commits_behind_main} commit(s) behind "
                f"{report.main_reference}; rebase it and push with --force-with-lease."
            )
        if branch.upstream_state == "none" and branch.commits_ahead_of_main:
            actions.append(f"{branch.name} has never been pushed.")
        if branch.upstream_state == "gone":
            actions.append(
                f"{branch.name}: its remote branch is gone but its content is not in "
                f"{report.main_reference}; check before deleting."
            )
    for branch in report.branches:
        if branch.worktree_uncommitted_change_count and not branch.is_current:
            actions.append(
                f"Worktree {branch.worktree_path} has {branch.worktree_uncommitted_change_count} "
                "uncommitted change(s); commit them, or check whether they are stale."
            )
    for pull_request in report.pull_requests:
        if pull_request.branch in merged_branch_names:
            actions.append(
                f"Pull request #{pull_request.number} is from a branch already in "
                f"{report.main_reference}; close it."
            )
    for submodule in report.submodules:
        if submodule.state != "ok":
            actions.append(
                f"Submodule {submodule.path} is {submodule.state}: "
                f"git submodule update --init --recursive {submodule.path}"
            )
    actions.extend(report.submodule_pin_problems)
    for issue in report.story_issues:
        if issue.merged_pull_request_number and issue.status in ACTIVE_ISSUE_STATUSES:
            close_step = (
                "run devops-tools close-merged-issue."
                if issue.story_file.startswith(f"{OPEN_ISSUES_DIRECTORY_NAME}/")
                else "move it to done.md."
            )
            actions.append(
                f"{issue.issue_id} was merged in #{issue.merged_pull_request_number} but is still "
                f"'{issue.status}' in {issue.story_file}; {close_step}"
            )
    return actions


def build_status_report(
    repository: Path,
    main_branch: str,
    should_fetch: bool,
    gh_executable: str | None,
    settings: RepositorySettings = DEFAULT_REPOSITORY_SETTINGS,
) -> StatusReport:
    if should_fetch:
        run_git(repository, "fetch", "--quiet", "--prune", "origin")
    remote_main = f"origin/{main_branch}"
    has_remote_main = run_git(repository, "rev-parse", "--verify", "--quiet", remote_main)
    main_reference = remote_main if has_remote_main.returncode == 0 else main_branch
    main_commit_subjects = git_output(repository, "log", "--format=%s", main_reference).splitlines()
    submodules: list[SubmoduleStatus] = []
    if (repository / ".gitmodules").exists():
        for line in run_git(repository, "submodule", "status").stdout.splitlines():
            submodule = parse_submodule_status_line(line)
            if submodule is not None:
                submodules.append(submodule)
    submodule_pin_problems: list[str] = []
    if should_fetch and submodules:
        try:
            for pin_check in check_submodule_pins(repository):
                if pin_check.status != STATUS_ON_BRANCH:
                    submodule_pin_problems.append(pin_check.message)
        except (OSError, RuntimeError, subprocess.SubprocessError) as pin_check_error:
            submodule_pin_problems.append(f"submodule pin check failed: {pin_check_error}")
    report = StatusReport(
        current_branch=git_output(repository, "branch", "--show-current") or "(detached HEAD)",
        uncommitted_change_count=count_uncommitted_changes(repository),
        main_reference=main_reference,
        main_commit_subject=main_commit_subjects[0] if main_commit_subjects else "",
        branches=list_local_branch_statuses(repository, main_reference, settings.issue_id_pattern),
        pull_requests=list_pull_request_statuses(repository, gh_executable),
        submodules=submodules,
        submodule_pin_problems=submodule_pin_problems,
        story_issues=list_story_issue_statuses(
            repository / settings.stories_directory,
            main_commit_subjects,
            find_issues_directory(repository, settings),
        ),
        suggested_actions=[],
    )
    return dataclasses.replace(report, suggested_actions=build_suggested_actions(report))


def render_status_report_text(report: StatusReport) -> str:
    lines = [
        f"On {report.current_branch} ({report.uncommitted_change_count} uncommitted change(s)); "
        f"{report.main_reference}: {report.main_commit_subject}",
        "",
        "Branches:",
    ]
    for branch in report.branches:
        details = [
            f"upstream {branch.upstream_state}",
            f"ahead {branch.commits_ahead_of_main}",
            f"behind {branch.commits_behind_main}",
        ]
        if branch.is_content_in_main:
            details.append("already in main")
        elif branch.merged_pull_request_number:
            details.append(f"merged in #{branch.merged_pull_request_number}")
        if branch.worktree_path:
            details.append(
                f"worktree {branch.worktree_path} "
                f"({branch.worktree_uncommitted_change_count} uncommitted)"
            )
        marker = "*" if branch.is_current else "-"
        lines.append(f"  {marker} {branch.name}: {', '.join(details)}")
    if not report.branches:
        lines.append("  (none besides main)")
    lines += ["", "Pull requests:"]
    for pull_request in report.pull_requests:
        lines.append(
            f"  #{pull_request.number} {pull_request.branch or '?'} "
            f"({pull_request.head_commit[:12]}, from {pull_request.source})"
        )
    if not report.pull_requests:
        lines.append("  (none open)")
    lines += ["", "Submodules:"]
    for submodule in report.submodules:
        lines.append(
            f"  {submodule.path} {submodule.pinned_or_checked_out_commit[:12]} {submodule.state}"
        )
    lines.extend(f"  {problem}" for problem in report.submodule_pin_problems)
    if not report.submodules:
        lines.append("  (none)")
    lines += ["", "Story issues:"]
    for issue in report.story_issues:
        merged = (
            f", merged in #{issue.merged_pull_request_number}"
            if issue.merged_pull_request_number
            else ""
        )
        lines.append(
            f"  {issue.issue_id} {issue.title} [{issue.status}{merged}] ({issue.story_file})"
        )
    lines += ["", "Suggested actions:"]
    lines.extend(f"  - {action}" for action in report.suggested_actions)
    if not report.suggested_actions:
        lines.append("  (nothing to do)")
    return "\n".join(lines)


def parse_arguments(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="devops-tools status-report",
        description="Report branches, worktrees, pull requests, submodules, and story issues.",
    )
    parser.add_argument("--repository", type=Path, help="Checkout to read (default: git top level)")
    parser.add_argument(
        "--settings-file",
        type=Path,
        help="pyproject.toml with [tool.devops-tools] (default: the repository's own)",
    )
    parser.add_argument("--main-branch", help="Default: main-branch from the settings")
    parser.add_argument("--no-fetch", action="store_true", help="Use the refs already fetched")
    parser.add_argument("--json", action="store_true", help="Print the report as JSON")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    arguments = parse_arguments(list(sys.argv[1:] if argv is None else argv))
    repository = (
        arguments.repository.resolve()
        if arguments.repository is not None
        else find_repository_root(Path.cwd())
    )
    try:
        settings = read_repository_settings(repository, arguments.settings_file)
    except RepositorySettingsError as settings_error:
        print(settings_error, file=sys.stderr)
        return EXIT_CODE_USAGE_ERROR
    report = build_status_report(
        repository,
        arguments.main_branch or settings.main_branch,
        should_fetch=not arguments.no_fetch,
        gh_executable=shutil.which("gh"),
        settings=settings,
    )
    if arguments.json:
        print(json.dumps(dataclasses.asdict(report), indent=2))
    else:
        print(render_status_report_text(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
