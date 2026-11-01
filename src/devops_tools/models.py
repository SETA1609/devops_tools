"""
Types shared by the devops_tools modules: dataclasses and type aliases.
"""

from __future__ import annotations

from dataclasses import dataclass

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
    Paths are relative to the repository root.
    """

    main_branch: str = DEFAULT_MAIN_BRANCH
    issue_id_pattern: str = DEFAULT_ISSUE_ID_PATTERN
    changes_directory: str = DEFAULT_CHANGES_DIRECTORY
    changelog_file: str = DEFAULT_CHANGELOG_FILE
