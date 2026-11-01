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
    DEFAULT_ISSUE_ID_PATTERN,
    DEFAULT_MAIN_BRANCH,
)


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
