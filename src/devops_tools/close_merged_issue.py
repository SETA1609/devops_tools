"""
Close the issue of a merged pull request, for projects that keep one file per issue:
    devops-tools close-merged-issue [--repository PATH] [--settings-file PATH]
        --branch NAME --pull-request-number N --merge-date YYYY-MM-DD
The issue comes from the branch name. An issue in `review` moves from `<issues-directory>/open`
to `<issues-directory>/done` with `Status: done` and a `Merged:` line; any other status stays
open, so a pull request that finishes only part of an issue does not close it. The story table
in the roadmap file is regenerated either way. Nothing is committed.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from devops_tools.changelog_fragments import compile_fragment_patterns
from devops_tools.constants import (
    DONE_ISSUES_DIRECTORY_NAME,
    EXIT_CODE_USAGE_ERROR,
    ISSUE_STATUS_LINE,
    MERGE_DATE_PATTERN,
    OPEN_ISSUES_DIRECTORY_NAME,
)
from devops_tools.container import find_repository_root
from devops_tools.exceptions import RepositorySettingsError
from devops_tools.models import RepositorySettings
from devops_tools.roadmap_order import regenerate_roadmap_story_table
from devops_tools.settings import read_repository_settings


def find_open_issue_file(open_directory: Path, issue_id: str) -> Path | None:
    """
    The file of `issue_id` in `open_directory`, ignoring case: branch names are lowercase.
    """
    for issue_file in sorted(open_directory.glob("*.md")):
        if issue_file.stem.lower() == issue_id.lower():
            return issue_file
    return None


def close_issue_of_branch(
    repository: Path,
    settings: RepositorySettings,
    branch_name: str,
    pull_request_number: int,
    merge_date: str,
) -> str:
    """
    Move the branch's issue to the done directory when it is in review, and return what
    happened in one line. Raises ValueError when the done directory already has that issue.
    """
    branch_match = compile_fragment_patterns(settings.issue_id_pattern).branch_issue_id.match(
        branch_name
    )
    if branch_match is None:
        return f"{branch_name}: no issue ID in the branch name; nothing to close"
    issues_directory = repository / settings.issues_directory
    issue_file = find_open_issue_file(
        issues_directory / OPEN_ISSUES_DIRECTORY_NAME, branch_match.group("issue_id")
    )
    if issue_file is None:
        return f"{branch_match.group('issue_id')}: no open issue file; nothing to close"
    issue_text = issue_file.read_text(encoding="utf-8")
    status_match = ISSUE_STATUS_LINE.search(issue_text)
    issue_status = status_match.group("status") if status_match else "todo"
    if status_match is None or issue_status != "review":
        return f"{issue_file.stem}: status is {issue_status}, not review; it stays open"
    done_file = issues_directory / DONE_ISSUES_DIRECTORY_NAME / issue_file.name
    if done_file.exists():
        raise ValueError(f"{done_file} already exists")
    closed_text = (
        issue_text[: status_match.start()]
        + f"- Status: done\n- Merged: #{pull_request_number}, {merge_date}"
        + issue_text[status_match.end() :]
    )
    done_file.parent.mkdir(parents=True, exist_ok=True)
    done_file.write_text(closed_text, encoding="utf-8")
    issue_file.unlink()
    return f"{issue_file.stem}: closed by #{pull_request_number}"


def parse_arguments(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="devops-tools close-merged-issue",
        description="Move the issue of a merged pull request to done and regenerate the roadmap.",
    )
    parser.add_argument("--repository", type=Path, help="Checkout to edit (default: git top level)")
    parser.add_argument(
        "--settings-file",
        type=Path,
        help="pyproject.toml with [tool.devops-tools] (default: the repository's own)",
    )
    parser.add_argument("--branch", required=True, help="The merged pull request's head branch")
    parser.add_argument("--pull-request-number", required=True, type=int)
    parser.add_argument("--merge-date", required=True, help="YYYY-MM-DD")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    arguments = parse_arguments(list(sys.argv[1:] if argv is None else argv))
    if not MERGE_DATE_PATTERN.fullmatch(arguments.merge_date):
        print(f"--merge-date must be YYYY-MM-DD, got: {arguments.merge_date}", file=sys.stderr)
        return EXIT_CODE_USAGE_ERROR
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
    if not settings.issues_directory:
        print("close-merged-issue needs the issues-directory setting", file=sys.stderr)
        return EXIT_CODE_USAGE_ERROR
    try:
        print(
            close_issue_of_branch(
                repository,
                settings,
                arguments.branch,
                arguments.pull_request_number,
                arguments.merge_date,
            )
        )
        regenerate_roadmap_story_table(repository, settings)
    except (ValueError, OSError) as close_error:
        print(close_error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
