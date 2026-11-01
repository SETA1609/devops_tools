"""
Changelog fragments: one file per issue in the changes directory, moved into the changelog at a
release. Each pull request adds `<changes-directory>/<issue-id>.md` with its entry, so open pull
requests never conflict on the top of the changelog.
    devops-tools changelog-fragments [--repository PATH] [--settings-file PATH] check [--branch B]
    devops-tools changelog-fragments [--repository PATH] [--settings-file PATH] preview
    devops-tools changelog-fragments [--repository PATH] [--settings-file PATH] release
        --section-title TITLE
check exits 1 and lists every problem when a fragment breaks a rule, or when --branch names an
issue that has no fragment.
"""

from __future__ import annotations

import argparse
import datetime
import functools
import re
import subprocess
import sys
from pathlib import Path

from devops_tools.constants import (
    CHANGELOG_LAST_UPDATED_LINE,
    CHANGELOG_SECTION_HEADING,
    CHANGES_README_FILE_NAME,
    PULL_REQUEST_NUMBER_IN_SUBJECT,
)
from devops_tools.exceptions import RepositorySettingsError
from devops_tools.models import (
    ChangelogFragment,
    FragmentCommit,
    FragmentPatterns,
    RepositorySettings,
)
from devops_tools.settings import read_repository_settings

DEFAULT_REPOSITORY_SETTINGS = RepositorySettings()


@functools.cache
def compile_fragment_patterns(issue_id_pattern: str) -> FragmentPatterns:
    return FragmentPatterns(
        file_name=re.compile(rf"^(?P<issue_id>{issue_id_pattern})\.md$"),
        heading=re.compile(rf"^### (?P<issue_id>{issue_id_pattern}) (?P<title>\S.*)$"),
        branch_issue_id=re.compile(
            rf"^(?:agent/[^/]+/)?(?P<issue_id>{issue_id_pattern})(?:-|$)", re.IGNORECASE
        ),
    )


def validate_changelog_fragment(
    file_name: str, text: str, settings: RepositorySettings = DEFAULT_REPOSITORY_SETTINGS
) -> list[str]:
    """
    Return one message per broken rule; an empty list means the fragment is valid.
    """
    patterns = compile_fragment_patterns(settings.issue_id_pattern)
    problems: list[str] = []
    file_name_match = patterns.file_name.match(file_name)
    if file_name_match is None:
        problems.append(
            f"{file_name}: file name must be an issue ID plus .md "
            f"(issue-id-pattern: {settings.issue_id_pattern})"
        )
    if not text.endswith("\n"):
        problems.append(f"{file_name}: must end with a newline")
    lines = text.splitlines()
    heading_match = patterns.heading.match(lines[0]) if lines else None
    if heading_match is None:
        problems.append(f"{file_name}: first line must be a heading: ### <issue-id> <title>")
    elif file_name_match is not None:
        heading_issue_id = heading_match.group("issue_id")
        file_issue_id = file_name_match.group("issue_id")
        if heading_issue_id != file_issue_id:
            problems.append(
                f"{file_name}: heading names {heading_issue_id}, file name names {file_issue_id}"
            )
    for line in lines[1:]:
        if line.startswith("#"):
            problems.append(f"{file_name}: only the first line may be a heading: {line}")
        if line.startswith("Status:"):
            problems.append(f"{file_name}: no Status line; status lives in the story file")
        if line.startswith("Last updated:"):
            problems.append(f"{file_name}: no Last updated line; a release sets it")
    if not any(line.startswith("- ") for line in lines[1:]):
        problems.append(f"{file_name}: needs at least one '- ' bullet")
    return problems


def read_changelog_fragment(
    path: Path, settings: RepositorySettings = DEFAULT_REPOSITORY_SETTINGS
) -> ChangelogFragment:
    """
    Read a fragment that validate_changelog_fragment accepted.
    """
    text = path.read_text(encoding="utf-8")
    heading_match = compile_fragment_patterns(settings.issue_id_pattern).heading.match(
        text.splitlines()[0]
    )
    assert heading_match is not None
    return ChangelogFragment(
        path=path,
        issue_id=heading_match.group("issue_id"),
        title=heading_match.group("title"),
        text=text,
    )


def list_changelog_fragment_paths(changes_directory: Path) -> list[Path]:
    """
    Every file in the changes directory except README.md, sorted by name. Files that are not
    fragments are listed too, so check reports them.
    """
    if not changes_directory.is_dir():
        return []
    return sorted(
        path
        for path in changes_directory.iterdir()
        if path.is_file() and path.name != CHANGES_README_FILE_NAME
    )


def find_issue_id_in_branch_name(
    branch_name: str, settings: RepositorySettings = DEFAULT_REPOSITORY_SETTINGS
) -> str | None:
    """
    `ab1.1-02-read-header` → `ab1.1-02`; `agent/claude/cd-04-pin` → `cd-04`; else None.
    Branch names are matched ignoring case.
    """
    branch_match = compile_fragment_patterns(settings.issue_id_pattern).branch_issue_id.match(
        branch_name
    )
    return branch_match.group("issue_id") if branch_match else None


def find_fragment_for_issue(changes_directory: Path, issue_id: str) -> Path | None:
    """
    The fragment whose file name is the issue ID, ignoring case (branches are lowercase).
    """
    wanted_file_name = f"{issue_id}.md".lower()
    for path in list_changelog_fragment_paths(changes_directory):
        if path.name.lower() == wanted_file_name:
            return path
    return None


def find_pull_request_number_in_subject(commit_subject: str) -> int | None:
    """
    `AB 18 rebase open pull requests onto main (#18)` → 18.
    """
    number_match = PULL_REQUEST_NUMBER_IN_SUBJECT.search(commit_subject)
    return int(number_match.group("number")) if number_match else None


def find_fragment_added_commit(repository: Path, fragment_path: Path) -> FragmentCommit | None:
    """
    The commit on HEAD that added the fragment, or None while it is uncommitted.
    """
    relative_path = fragment_path.resolve().relative_to(repository.resolve())
    completed = run_git(
        repository,
        "log",
        "--diff-filter=A",
        "--format=%H%x00%ct%x00%s",
        "-1",
        "HEAD",
        "--",
        relative_path.as_posix(),
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        return None
    commit_sha, committed_at, subject = completed.stdout.strip().split("\x00", 2)
    return FragmentCommit(
        commit_sha=commit_sha,
        committed_at_unix_seconds=int(committed_at),
        pull_request_number=find_pull_request_number_in_subject(subject),
    )


def render_changelog_entries(
    fragments_with_commits: list[tuple[ChangelogFragment, FragmentCommit | None]],
    should_append_pull_request_numbers: bool,
) -> str:
    """
    The entries newest first (uncommitted ones first of all), ties by issue ID, each
    followed by one blank line. Headings get ` (#N)` when asked and the number is known.
    """

    def newest_first(entry: tuple[ChangelogFragment, FragmentCommit | None]) -> tuple:
        fragment, commit = entry
        is_committed = commit is not None
        committed_at = commit.committed_at_unix_seconds if commit is not None else 0
        return (is_committed, -committed_at, fragment.issue_id)

    rendered_entries: list[str] = []
    for fragment, commit in sorted(fragments_with_commits, key=newest_first):
        heading, _, rest = fragment.text.partition("\n")
        if should_append_pull_request_numbers and commit and commit.pull_request_number:
            heading = f"{heading} (#{commit.pull_request_number})"
        rendered_entries.append(f"{heading}\n{rest.rstrip()}\n\n")
    return "".join(rendered_entries)


def insert_release_section(
    changelog_text: str,
    section_title: str,
    entries_text: str,
    last_updated: str,
) -> str:
    """
    Put `## <section_title>` and the entries before the first `## ` section and set
    `Last updated:`.
    """
    updated = CHANGELOG_LAST_UPDATED_LINE.sub(
        f"Last updated: {last_updated}", changelog_text, count=1
    )
    new_section = f"## {section_title}\n\n{entries_text}"
    first_section_match = CHANGELOG_SECTION_HEADING.search(updated)
    if first_section_match is None:
        return updated.rstrip("\n") + "\n\n" + new_section.rstrip("\n") + "\n"
    position = first_section_match.start()
    return updated[:position] + new_section + updated[position:]


def release_changelog_fragments(
    repository: Path,
    section_title: str,
    now: datetime.datetime,
    settings: RepositorySettings = DEFAULT_REPOSITORY_SETTINGS,
) -> list[Path]:
    """
    Move every fragment into the changelog and delete it. Returns the deleted paths.
    """
    changes_directory = repository / settings.changes_directory
    fragment_paths = list_changelog_fragment_paths(changes_directory)
    if not fragment_paths:
        raise ValueError(f"{changes_directory}: no fragments to release")
    problems = validate_changelog_fragment_files(fragment_paths, settings)
    if problems:
        raise ValueError("\n".join(problems))
    fragments_with_commits = [
        (read_changelog_fragment(path, settings), find_fragment_added_commit(repository, path))
        for path in fragment_paths
    ]
    entries_text = render_changelog_entries(
        fragments_with_commits, should_append_pull_request_numbers=True
    )
    changelog_path = repository / settings.changelog_file
    changelog_text = changelog_path.read_text(encoding="utf-8")
    last_updated = now.astimezone(datetime.UTC).strftime("%Y-%m-%dT%H:%MZ")
    changelog_path.write_text(
        insert_release_section(changelog_text, section_title, entries_text, last_updated),
        encoding="utf-8",
    )
    for path in fragment_paths:
        path.unlink()
    return fragment_paths


def check_changelog_fragments(
    repository: Path,
    branch_name: str | None,
    settings: RepositorySettings = DEFAULT_REPOSITORY_SETTINGS,
) -> list[str]:
    """
    Problems with all fragments, plus a missing fragment for the branch's issue.
    """
    changes_directory = repository / settings.changes_directory
    problems = validate_changelog_fragment_files(
        list_changelog_fragment_paths(changes_directory), settings
    )
    if branch_name is None:
        return problems
    issue_id = find_issue_id_in_branch_name(branch_name, settings)
    if issue_id is None:
        problems.append(
            f"branch {branch_name}: name does not start with an issue ID "
            "(<issue-id>-<slug> or agent/<name>/<issue-id>-<slug>)"
        )
    elif find_fragment_for_issue(changes_directory, issue_id) is None:
        problems.append(
            f"branch {branch_name}: no fragment for issue {issue_id}; "
            f"add {settings.changes_directory}/<issue-id>.md, spelled as in the issue tracker"
        )
    return problems


def validate_changelog_fragment_files(
    fragment_paths: list[Path], settings: RepositorySettings = DEFAULT_REPOSITORY_SETTINGS
) -> list[str]:
    """
    validate_changelog_fragment for each file, reading it as UTF-8.
    """
    problems: list[str] = []
    for path in fragment_paths:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as read_error:
            problems.append(f"{path.name}: cannot read: {read_error}")
            continue
        problems.extend(validate_changelog_fragment(path.name, text, settings))
    return problems


def run_git(repository: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repository), *args],
        check=False,
        capture_output=True,
        text=True,
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="devops-tools changelog-fragments",
        description="Check, preview, and release changelog fragments.",
    )
    parser.add_argument("--repository", type=Path, default=Path("."), help="Path to the checkout")
    parser.add_argument(
        "--settings-file",
        type=Path,
        help="pyproject.toml with [tool.devops-tools] (default: the repository's own)",
    )
    subcommands = parser.add_subparsers(dest="subcommand", required=True)
    check_parser = subcommands.add_parser("check", help="Validate the fragments")
    check_parser.add_argument("--branch", help="Also require the fragment for this branch's issue")
    subcommands.add_parser("preview", help="Print the unreleased entries")
    release_parser = subcommands.add_parser("release", help="Move the fragments into the changelog")
    release_parser.add_argument("--section-title", required=True, help="Heading of the new section")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(list(sys.argv[1:] if argv is None else argv))
    repository = args.repository.resolve()
    try:
        settings = read_repository_settings(repository, args.settings_file)
    except RepositorySettingsError as settings_error:
        print(settings_error, file=sys.stderr)
        return 2
    if args.subcommand == "check":
        problems = check_changelog_fragments(repository, args.branch, settings)
        for problem in problems:
            print(problem)
        if problems:
            rules_path = f"{settings.changes_directory}/{CHANGES_README_FILE_NAME}"
            print(f"{len(problems)} problem(s); the rules are in {rules_path}")
            return 1
        print("Changelog fragments are valid.")
        return 0
    changes_directory = repository / settings.changes_directory
    if args.subcommand == "preview":
        fragment_paths = list_changelog_fragment_paths(changes_directory)
        problems = validate_changelog_fragment_files(fragment_paths, settings)
        if problems:
            for problem in problems:
                print(problem, file=sys.stderr)
            return 1
        fragments_with_commits = [
            (read_changelog_fragment(path, settings), find_fragment_added_commit(repository, path))
            for path in fragment_paths
        ]
        entries_text = render_changelog_entries(
            fragments_with_commits, should_append_pull_request_numbers=False
        )
        print(f"## Unreleased\n\n{entries_text}".rstrip("\n"))
        return 0
    try:
        deleted_paths = release_changelog_fragments(
            repository, args.section_title, datetime.datetime.now(datetime.UTC), settings
        )
    except ValueError as release_error:
        print(release_error, file=sys.stderr)
        return 1
    for path in deleted_paths:
        print(f"Released and deleted {path.relative_to(repository).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
