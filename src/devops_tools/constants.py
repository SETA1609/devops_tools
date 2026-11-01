"""
Constants shared by the devops_tools modules.
"""

from __future__ import annotations

# Run log
RUN_LOG_FILE_SUFFIX = ".log"
OLDER_THAN_DAYS_FLAG = "--older-than-days"
SECONDS_PER_DAY = 86_400
EXIT_CODE_PROGRAM_NOT_FOUND = 127
EXIT_CODE_SIGNAL_BASE = 128

# CLI exit codes
EXIT_CODE_SETUP_ERROR = 1
EXIT_CODE_USAGE_ERROR = 2

# CLI
DEFAULT_LOG_DIRECTORY = "cache/logs"
LOG_DIRECTORY_FLAG = "--log-directory"
LOG_NAME_PATTERN = r"[A-Za-z0-9][A-Za-z0-9._-]*"

# Repository settings: `[tool.devops-tools]` in pyproject.toml
SETTINGS_FILE_NAME = "pyproject.toml"
SETTINGS_TABLE_PATH = ("tool", "devops-tools")
DEFAULT_MAIN_BRANCH = "main"
# Letters and digits, an optional `.N`, then a dash and a number: AB-12, AB1.1-02, issue-3.
DEFAULT_ISSUE_ID_PATTERN = r"[A-Za-z][A-Za-z0-9]*(?:\.[0-9]+)?-[0-9]+"
DEFAULT_CHANGES_DIRECTORY = "changes"
DEFAULT_CHANGELOG_FILE = "CHANGELOG.md"
