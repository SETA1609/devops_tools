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
