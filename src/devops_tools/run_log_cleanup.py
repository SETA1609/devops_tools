"""
Pruning old run logs in a log directory. `devops-tools prune-logs` uses this.
Only `*.log` files directly in the log directory are removed; other files, subdirectories,
symlinks, and the log of the run doing the pruning are never touched.
"""

from __future__ import annotations

import datetime
from collections.abc import Sequence
from pathlib import Path

from devops_tools.constants import OLDER_THAN_DAYS_FLAG, RUN_LOG_FILE_SUFFIX, SECONDS_PER_DAY
from devops_tools.exceptions import RunLogCleanupUsageError


def parse_older_than_days_argument(extra_arguments: Sequence[str]) -> int:
    """
    `[]` → 0 (every log); `["--older-than-days", "7"]` → 7. Anything else is a usage error.
    """
    if not extra_arguments:
        return 0
    if len(extra_arguments) != 2 or extra_arguments[0] != OLDER_THAN_DAYS_FLAG:
        raise RunLogCleanupUsageError(
            f"prune-logs takes only {OLDER_THAN_DAYS_FLAG} <days>, got: {' '.join(extra_arguments)}"
        )
    try:
        older_than_days = int(extra_arguments[1])
    except ValueError as conversion_error:
        raise RunLogCleanupUsageError(
            f"{OLDER_THAN_DAYS_FLAG} needs a whole number of days, got: {extra_arguments[1]}"
        ) from conversion_error
    if older_than_days < 0:
        raise RunLogCleanupUsageError(
            f"{OLDER_THAN_DAYS_FLAG} cannot be negative, got: {older_than_days}"
        )
    return older_than_days


def select_run_log_files_to_remove(
    log_directory: Path,
    current_run_log_path: Path | None,
    older_than_days: int,
    current_moment: datetime.datetime,
) -> list[Path]:
    """
    Run logs last modified more than `older_than_days` days before `current_moment`, sorted
    by name (oldest first). With 0 days, every run log except the current run's.
    """
    if not log_directory.is_dir():
        return []
    cutoff_timestamp_seconds = current_moment.timestamp() - older_than_days * SECONDS_PER_DAY
    current_run_log_resolved = (
        current_run_log_path.resolve() if current_run_log_path is not None else None
    )
    selected_paths: list[Path] = []
    for candidate_path in sorted(log_directory.iterdir()):
        if candidate_path.is_symlink() or not candidate_path.is_file():
            continue
        if candidate_path.suffix != RUN_LOG_FILE_SUFFIX:
            continue
        if candidate_path.resolve() == current_run_log_resolved:
            continue
        if older_than_days > 0 and candidate_path.stat().st_mtime >= cutoff_timestamp_seconds:
            continue
        selected_paths.append(candidate_path)
    return selected_paths
