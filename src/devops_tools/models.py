"""
Types shared by the devops_tools modules: dataclasses and type aliases.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from devops_tools.constants import (
    DEFAULT_CHANGELOG_FILE,
    DEFAULT_CHANGES_DIRECTORY,
    DEFAULT_CONTAINER_HOME_DIRECTORY,
    DEFAULT_DOCKERFILE,
    DEFAULT_ISSUE_ID_PATTERN,
    DEFAULT_MAIN_BRANCH,
    DEFAULT_PROTECTED_DIRECTORIES,
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
    """

    main_branch: str = DEFAULT_MAIN_BRANCH
    issue_id_pattern: str = DEFAULT_ISSUE_ID_PATTERN
    changes_directory: str = DEFAULT_CHANGES_DIRECTORY
    changelog_file: str = DEFAULT_CHANGELOG_FILE
    keep_both_added_lines: tuple[str, ...] = ()
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
