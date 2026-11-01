"""
Types shared by the devops_tools modules: dataclasses and type aliases.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from devops_tools.constants import (
    DEFAULT_AGENT_HOME_VOLUME,
    DEFAULT_CHANGELOG_FILE,
    DEFAULT_CHANGES_DIRECTORY,
    DEFAULT_CONTAINER_HOME_DIRECTORY,
    DEFAULT_DOCKERFILE,
    DEFAULT_DOCS_CACHE_DIRECTORY,
    DEFAULT_FOCUS_FILE,
    DEFAULT_ISSUE_ID_PATTERN,
    DEFAULT_MAIN_BRANCH,
    DEFAULT_PROTECTED_DIRECTORIES,
    DEFAULT_ROADMAP_FILE,
    DEFAULT_STORIES_DIRECTORY,
)


@dataclass(frozen=True)
class VersionPin:
    """
    A file that must name the toolchain version: `pattern` has one group that captures it.
    """

    file: str
    pattern: str


@dataclass(frozen=True)
class ContainerSettings:
    """
    The `[tool.devops-tools.container]` table: what the toolchain container runner needs.
    With `version_file`, the image tag is `<image>:<toolchain>-<version>` and the Dockerfile's
    `ARG <version_argument>=` must match it; without, the tag is `<image>:latest`.
    `commands` maps a subcommand name to the command it runs in the container.
    `agent_setup_commands` run in the checkout each time the agent container starts.
    Paths are relative to the repository root.
    """

    image: str
    dockerfile: str = DEFAULT_DOCKERFILE
    toolchain: str = "toolchain"
    version_file: str | None = None
    version_argument: str | None = None
    version_pins: tuple[VersionPin, ...] = ()
    home_directory: str = DEFAULT_CONTAINER_HOME_DIRECTORY
    cache_environment_variable: str | None = None
    cache_volume: str | None = None
    read_only_symlink_mounts: tuple[str, ...] = ()
    clean_directories: tuple[str, ...] = ()
    protected_directories: tuple[str, ...] = DEFAULT_PROTECTED_DIRECTORIES
    commands: tuple[tuple[str, tuple[str, ...]], ...] = ()
    agent_home_volume: str = DEFAULT_AGENT_HOME_VOLUME
    agent_setup_commands: tuple[tuple[str, ...], ...] = ()
    agent_claude_code_version: str | None = None


@dataclass(frozen=True)
class ContainerRunSettings:
    """
    What every `<binary> run` needs, whatever command it runs. `user_and_group_ids` is None to
    run as root. `git_common_directory` is set when the git directory lives outside the
    checkout (a worktree or a submodule), so it is mounted too. With `keep_cache`, the cache
    lives in the named volume instead of the throwaway home.
    """

    container_binary: str
    repository_root: Path
    image: str
    user_and_group_ids: tuple[int, int] | None
    git_common_directory: Path | None
    read_only_mount_paths: tuple[Path, ...]
    keep_cache: bool = False


@dataclass(frozen=True)
class RepositorySettings:
    """
    The `[tool.devops-tools]` table of a project: what the repository workflow tools read.
    `issue_id_pattern` is a regular expression for one issue ID, without anchors or named groups.
    Paths are relative to the repository root. `keep_both_added_lines` holds gitattributes
    patterns of more files whose added-lines conflicts the rebase resolves like the changelog's.
    `stories_directory` holds one Markdown file per story track; `roadmap_file` gets the
    generated story order table; `focus_file` holds the owner's `Focus:` line;
    `docs_cache_directory` is where fetch-docs saves downloads.
    """

    main_branch: str = DEFAULT_MAIN_BRANCH
    issue_id_pattern: str = DEFAULT_ISSUE_ID_PATTERN
    changes_directory: str = DEFAULT_CHANGES_DIRECTORY
    changelog_file: str = DEFAULT_CHANGELOG_FILE
    keep_both_added_lines: tuple[str, ...] = ()
    stories_directory: str = DEFAULT_STORIES_DIRECTORY
    roadmap_file: str = DEFAULT_ROADMAP_FILE
    focus_file: str = DEFAULT_FOCUS_FILE
    docs_cache_directory: str = DEFAULT_DOCS_CACHE_DIRECTORY
    container: ContainerSettings | None = None


@dataclass(frozen=True)
class FragmentPatterns:
    """
    The issue ID pattern compiled into the three places a fragment check looks for an ID:
    the file name `<issue-id>.md`, the heading `### <issue-id> <title>`, and a branch name
    `<issue-id>-<slug>` or `agent/<agent-name>/<issue-id>-<slug>`.
    """

    file_name: re.Pattern[str]
    heading: re.Pattern[str]
    branch_issue_id: re.Pattern[str]


@dataclass(frozen=True)
class ChangelogFragment:
    """
    One `<changes-directory>/<issue-id>.md` file: its issue, title, and full text.
    """

    path: Path
    issue_id: str
    title: str
    text: str


@dataclass(frozen=True)
class FragmentCommit:
    """
    The commit that added a fragment: when, and the pull request number from a squash merge.
    """

    commit_sha: str
    committed_at_unix_seconds: int
    pull_request_number: int | None


@dataclass(frozen=True)
class SubmodulePin:
    """
    One submodule pointer at HEAD and where its upstream lives.
    """

    path: str
    url: str
    pinned_commit: str
    branch: str | None


@dataclass(frozen=True)
class SubmodulePinCheck:
    """
    The result for one pin; suggested_commit is set only for not_on_branch with a tree match.
    """

    path: str
    url: str
    pinned_commit: str
    branch: str | None
    status: str
    suggested_commit: str | None
    message: str


@dataclass(frozen=True)
class RoadmapIssue:
    """
    One `#### <issue-id> <title>` entry in a story file: its story, status, and needed issues.
    """

    issue_id: str
    title: str
    story_id: str
    status: str
    needed_issue_ids: tuple[str, ...]


@dataclass(frozen=True)
class BranchStatus:
    """
    One local branch compared with the main branch on origin.
    upstream_state: tracking, gone (its remote branch was deleted), or none (never pushed).
    merged_pull_request_number: set when a main commit names the branch's issue with `(#N)`,
    which also catches squash merges of a branch that was rebased after the local copy.
    """

    name: str
    upstream_state: str
    commits_ahead_of_main: int
    commits_behind_main: int
    is_content_in_main: bool
    merged_pull_request_number: int | None
    is_current: bool
    worktree_path: str | None
    worktree_uncommitted_change_count: int


@dataclass(frozen=True)
class PullRequestStatus:
    """
    A pull request on origin. source: gh (open pull requests) or refs (refs/pull/*/head whose
    head is still a remote branch tip, so probably open).
    """

    number: int
    branch: str | None
    head_commit: str
    source: str


@dataclass(frozen=True)
class SubmoduleStatus:
    """
    One line of `git submodule status`: state is ok, not_at_pin, not_initialized, or conflict.
    """

    path: str
    pinned_or_checked_out_commit: str
    state: str


@dataclass(frozen=True)
class StoryIssueStatus:
    """
    An issue in the story files that is active (doing, review) or the next todo of its file.
    """

    issue_id: str
    title: str
    status: str
    story_file: str
    merged_pull_request_number: int | None


@dataclass(frozen=True)
class StatusReport:
    """
    Everything the status report prints.
    """

    current_branch: str
    uncommitted_change_count: int
    main_reference: str
    main_commit_subject: str
    branches: list[BranchStatus]
    pull_requests: list[PullRequestStatus]
    submodules: list[SubmoduleStatus]
    submodule_pin_problems: list[str]
    story_issues: list[StoryIssueStatus]
    suggested_actions: list[str]


@dataclass(frozen=True)
class FetchedDocument:
    """
    One downloaded URL: where it came from, where it is saved, and its size.
    """

    source_url: str
    cache_file_path: Path
    byte_count: int
