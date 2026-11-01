"""
Order keywords for a roadmap kept as story files: which issues and stories come first, which
are ready and can run in parallel, which are blocked and by what, and which lie on the critical
path. The only hand-written inputs are each issue's `Status` and `Needs` lines and the owner's
`Focus:` line.
    devops-tools roadmap-order [--repository PATH] [--settings-file PATH] show|write|check
show prints the issue view; write regenerates the story table in the roadmap file between its
begin and end markers; check exits 1 when that table is stale. Issues in `done` or `review`
count as finished; `dropped` issues are ignored.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

from devops_tools.constants import (
    DONE_STORY_FILE_NAME,
    EXIT_CODE_USAGE_ERROR,
    FINISHED_ISSUE_STATUSES,
    FOCUS_LINE,
    ISSUE_NEEDS_LINE,
    ISSUE_STATUS_LINE,
    ROADMAP_TABLE_BEGIN,
    ROADMAP_TABLE_END,
    STORY_HEADING,
)
from devops_tools.container import find_repository_root
from devops_tools.exceptions import RepositorySettingsError
from devops_tools.models import RepositorySettings, RoadmapIssue
from devops_tools.settings import read_repository_settings

DEFAULT_REPOSITORY_SETTINGS = RepositorySettings()


def find_story_id_of_issue(issue_id: str) -> str:
    return issue_id.rsplit("-", 1)[0]


def read_roadmap_issues(
    stories_directory: Path, issue_id_pattern: str = DEFAULT_REPOSITORY_SETTINGS.issue_id_pattern
) -> tuple[dict[str, RoadmapIssue], list[str]]:
    """
    Every issue in the story files and done.md, and the story IDs in file and heading order.
    """
    issue_block_pattern = re.compile(
        rf"^#### (?P<issue_id>{issue_id_pattern}) (?P<title>.*)\n(?P<body>(?:[- ].*\n)*)",
        re.MULTILINE,
    )
    issues_by_id: dict[str, RoadmapIssue] = {}
    story_ids_in_order: list[str] = []
    for story_file in sorted(stories_directory.glob("*.md")):
        if story_file.name == "README.md":
            continue
        story_text = story_file.read_text(encoding="utf-8")
        if story_file.name != DONE_STORY_FILE_NAME:
            for story_match in STORY_HEADING.finditer(story_text):
                if story_match.group("story_id") not in story_ids_in_order:
                    story_ids_in_order.append(story_match.group("story_id"))
        for issue_match in issue_block_pattern.finditer(story_text):
            body = issue_match.group("body")
            status_match = ISSUE_STATUS_LINE.search(body)
            needs_match = ISSUE_NEEDS_LINE.search(body)
            issue_id = issue_match.group("issue_id")
            needed_issue_ids = (
                tuple(re.findall(issue_id_pattern, needs_match.group("needs")))
                if needs_match
                else ()
            )
            issues_by_id[issue_id] = RoadmapIssue(
                issue_id=issue_id,
                title=issue_match.group("title").strip(),
                story_id=find_story_id_of_issue(issue_id),
                status=status_match.group("status") if status_match else "todo",
                needed_issue_ids=needed_issue_ids,
            )
    return issues_by_id, story_ids_in_order


def read_focus_story_ids(focus_file_text: str) -> list[str]:
    """
    `Focus: AB, CD` → ["AB", "CD"]: the owner's order, first to last.
    """
    focus_match = FOCUS_LINE.search(focus_file_text)
    if focus_match is None:
        return []
    return [
        story_id.strip() for story_id in focus_match.group("focus").split(",") if story_id.strip()
    ]


def is_issue_open(issue: RoadmapIssue) -> bool:
    return issue.status not in (*FINISHED_ISSUE_STATUSES, "dropped")


def list_unfinished_needs(issue: RoadmapIssue, issues_by_id: dict[str, RoadmapIssue]) -> list[str]:
    """
    The needed issues that are still open. An unknown ID counts as open, so a typo blocks.
    """
    return [
        needed_id
        for needed_id in issue.needed_issue_ids
        if needed_id not in issues_by_id or is_issue_open(issues_by_id[needed_id])
    ]


def compute_issue_waves(issues_by_id: dict[str, RoadmapIssue]) -> dict[str, int]:
    """
    Wave of each open issue: 0 when nothing open blocks it, else one more than its latest
    open blocker. Issues in one wave can run in parallel once the earlier waves are merged.
    A dependency cycle raises ValueError naming an issue on it.
    """
    waves: dict[str, int] = {}
    visiting: set[str] = set()

    def compute_wave(issue_id: str) -> int:
        if issue_id in waves:
            return waves[issue_id]
        if issue_id in visiting:
            raise ValueError(f"dependency cycle through {issue_id}")
        visiting.add(issue_id)
        blocker_waves = [
            compute_wave(needed_id)
            for needed_id in list_unfinished_needs(issues_by_id[issue_id], issues_by_id)
            if needed_id in issues_by_id
        ]
        visiting.discard(issue_id)
        waves[issue_id] = max(blocker_waves, default=-1) + 1
        return waves[issue_id]

    for issue in issues_by_id.values():
        if is_issue_open(issue):
            compute_wave(issue.issue_id)
    return waves


def find_critical_path(issues_by_id: dict[str, RoadmapIssue], waves: dict[str, int]) -> list[str]:
    """
    The longest chain of open issues, first to last: walk back from the deepest issue through
    its deepest open blocker. Ties go to the lower issue ID.
    """
    if not waves:
        return []
    deepest_issue_id = min(waves, key=lambda issue_id: (-waves[issue_id], issue_id))
    critical_path = [deepest_issue_id]
    while waves[critical_path[-1]] > 0:
        blockers = [
            needed_id
            for needed_id in list_unfinished_needs(issues_by_id[critical_path[-1]], issues_by_id)
            if needed_id in waves
        ]
        critical_path.append(min(blockers, key=lambda issue_id: (-waves[issue_id], issue_id)))
    return list(reversed(critical_path))


def compute_story_blockers(issues_by_id: dict[str, RoadmapIssue]) -> dict[str, set[str]]:
    """
    For each story, the other stories whose open issues its open issues need.
    """
    story_blockers: dict[str, set[str]] = defaultdict(set)
    for issue in issues_by_id.values():
        if not is_issue_open(issue):
            continue
        for needed_id in list_unfinished_needs(issue, issues_by_id):
            needed_story_id = find_story_id_of_issue(needed_id)
            if needed_story_id != issue.story_id:
                story_blockers[issue.story_id].add(needed_story_id)
    return story_blockers


def build_story_table(
    issues_by_id: dict[str, RoadmapIssue], story_ids_in_order: list[str], focus_story_ids: list[str]
) -> str:
    """
    The Markdown table for the roadmap file: one row per story with open issues, in story file
    order, with its wave (the earliest wave of its open issues), keywords, and blockers.
    """
    waves = compute_issue_waves(issues_by_id)
    story_blockers = compute_story_blockers(issues_by_id)
    critical_story_ids = {
        find_story_id_of_issue(issue_id) for issue_id in find_critical_path(issues_by_id, waves)
    }
    rows = [
        "| Wave | Story | Keyword | Blocked by | Open issues |",
        "|---|---|---|---|---|",
    ]
    for story_id in story_ids_in_order:
        open_issue_ids = [
            issue.issue_id
            for issue in issues_by_id.values()
            if issue.story_id == story_id and is_issue_open(issue)
        ]
        if not open_issue_ids:
            continue
        story_wave = min(waves[issue_id] for issue_id in open_issue_ids)
        keywords = []
        if story_id in focus_story_ids:
            keywords.append(f"first ({focus_story_ids.index(story_id) + 1})")
        keywords.append("ready" if story_wave == 0 else "blocked")
        if story_id in critical_story_ids:
            keywords.append("critical")
        blocker_text = ", ".join(sorted(story_blockers.get(story_id, ()))) or "—"
        keyword_text = ", ".join(keywords)
        open_count = len(open_issue_ids)
        rows.append(
            f"| {story_wave} | {story_id} | {keyword_text} | {blocker_text} | {open_count} |"
        )
    return "\n".join(rows) + "\n"


def build_issue_view(issues_by_id: dict[str, RoadmapIssue], focus_story_ids: list[str]) -> str:
    """
    The `show` text: first, ready in parallel, the critical path, and blocked issues by wave.
    """
    waves = compute_issue_waves(issues_by_id)
    ready_ids = sorted(issue_id for issue_id, wave in waves.items() if wave == 0)

    def describe(issue_id: str) -> str:
        issue = issues_by_id[issue_id]
        status_text = "" if issue.status == "todo" else f" [{issue.status}]"
        return f"{issue_id} {issue.title}{status_text}"

    first_ids = [
        issue_id
        for story_id in focus_story_ids
        for issue_id in ready_ids
        if issues_by_id[issue_id].story_id == story_id
    ]
    lines = [
        f"Focus: {', '.join(focus_story_ids) or '(none)'}",
        "",
        "first (ready, in focus order):",
    ]
    lines += [f"  {describe(issue_id)}" for issue_id in first_ids] or ["  (none)"]
    lines += ["", "ready, can run in parallel (separate branches or worktrees):"]
    lines += [f"  {describe(issue_id)}" for issue_id in ready_ids if issue_id not in first_ids] or [
        "  (none)"
    ]
    critical_path = find_critical_path(issues_by_id, waves)
    lines += ["", f"critical path ({len(critical_path)} issues; a delay here delays the end):"]
    lines += ["  " + " → ".join(critical_path[:12]) + (" → …" if len(critical_path) > 12 else "")]
    lines += ["", "blocked, by wave (a wave can run in parallel once the earlier ones are merged):"]
    for wave in range(1, min(max(waves.values(), default=0), 6) + 1):
        wave_ids = sorted(issue_id for issue_id, issue_wave in waves.items() if issue_wave == wave)
        lines.append(f"  wave {wave}: {len(wave_ids)} issues")
        for issue_id in wave_ids[:8]:
            blockers = ", ".join(list_unfinished_needs(issues_by_id[issue_id], issues_by_id))
            lines.append(f"    {issue_id} blocked by {blockers}")
        if len(wave_ids) > 8:
            lines.append(f"    … {len(wave_ids) - 8} more")
    return "\n".join(lines) + "\n"


def replace_story_table(roadmap_text: str, story_table: str) -> str:
    """
    The roadmap text with everything between the begin and end markers replaced by the table.
    """
    if ROADMAP_TABLE_BEGIN not in roadmap_text or ROADMAP_TABLE_END not in roadmap_text:
        raise ValueError(
            f"the roadmap file needs the markers {ROADMAP_TABLE_BEGIN} and {ROADMAP_TABLE_END}"
        )
    begin_marker_position = roadmap_text.index(ROADMAP_TABLE_BEGIN)
    begin_position = roadmap_text.index("-->", begin_marker_position) + len("-->")
    end_position = roadmap_text.index(ROADMAP_TABLE_END)
    return roadmap_text[:begin_position] + "\n\n" + story_table + "\n" + roadmap_text[end_position:]


def parse_arguments(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="devops-tools roadmap-order",
        description="Order keywords (first, ready, wave, blocked, critical) for story files.",
    )
    parser.add_argument("action", choices=("show", "write", "check"))
    parser.add_argument("--repository", type=Path, help="Checkout to read (default: git top level)")
    parser.add_argument(
        "--settings-file",
        type=Path,
        help="pyproject.toml with [tool.devops-tools] (default: the repository's own)",
    )
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
    issues_by_id, story_ids_in_order = read_roadmap_issues(
        repository / settings.stories_directory, settings.issue_id_pattern
    )
    focus_path = repository / settings.focus_file
    focus_story_ids = (
        read_focus_story_ids(focus_path.read_text(encoding="utf-8")) if focus_path.is_file() else []
    )
    roadmap_path = repository / settings.roadmap_file
    try:
        if arguments.action == "show":
            print(build_issue_view(issues_by_id, focus_story_ids), end="")
            return 0
        story_table = build_story_table(issues_by_id, story_ids_in_order, focus_story_ids)
        roadmap_text = roadmap_path.read_text(encoding="utf-8")
        updated_text = replace_story_table(roadmap_text, story_table)
    except (ValueError, OSError) as roadmap_error:
        print(roadmap_error, file=sys.stderr)
        return 1
    if arguments.action == "write":
        roadmap_path.write_text(updated_text, encoding="utf-8")
        return 0
    if updated_text != roadmap_text:
        print(f"{settings.roadmap_file} is stale: run devops-tools roadmap-order write")
        return 1
    print(f"{settings.roadmap_file} order table is current.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
