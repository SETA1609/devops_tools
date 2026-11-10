"""
`devops-tools [--log-directory DIR] <subcommand> [args...]`.
`run` and `prune-logs` write `<log-directory>/<utc-timestamp>-<name>.log` (default `cache/logs`
under the current directory). The repository workflow subcommands print plain output for CI;
wrap one in `run` to log it. Each exits with the exit code of what it ran.
"""

from __future__ import annotations

import functools
import re
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from devops_tools import (
    changelog_fragments,
    check_submodule_pins,
    close_merged_issue,
    container_cli,
    fetch_docs,
    rebase_open_branches,
    roadmap_order,
    status_report,
)
from devops_tools.constants import (
    DEFAULT_LOG_DIRECTORY,
    EXIT_CODE_SETUP_ERROR,
    EXIT_CODE_USAGE_ERROR,
    LOG_DIRECTORY_FLAG,
    LOG_NAME_PATTERN,
    OLDER_THAN_DAYS_FLAG,
)
from devops_tools.exceptions import CommandLineUsageError, RunLogCleanupUsageError
from devops_tools.run_log import (
    RunLog,
    get_current_utc_time,
    run_command_with_timestamped_output,
    run_with_run_log,
)
from devops_tools.run_log_cleanup import (
    parse_older_than_days_argument,
    select_run_log_files_to_remove,
)

USAGE_TEXT = f"""usage: devops-tools [{LOG_DIRECTORY_FLAG} DIR] <subcommand> [args...]

  run <name> [--] <command> [args...]
             run a command; timestamp and log every output line as <name>
  prune-logs [{OLDER_THAN_DAYS_FLAG} N]
             remove run logs (all, or older than N days); keeps this run's

Repository workflow (settings: [tool.devops-tools] in pyproject.toml; --help on each):
  rebase-open-branches   rebase open pull requests onto the main branch and push them
  changelog-fragments    check, preview, or release changes/<issue-id>.md fragments
  check-submodule-pins   check that every submodule pin is on its upstream branch
  status-report          where the work stands: branches, pull requests, story issues
  roadmap-order          show, write, or check first / ready / blocked order keywords
  close-merged-issue     move a merged issue file to done and regenerate the roadmap
  fetch-docs             download docs, specs, and sources into the local cache

Toolchain container (settings: [tool.devops-tools.container]; logged to cache/logs):
  container <action>     image, exec, shell, prune, clean, or a named command

Logs go to {LOG_DIRECTORY_FLAG} (default {DEFAULT_LOG_DIRECTORY} under the current directory)."""

REPOSITORY_WORKFLOW_SUBCOMMANDS: dict[str, Callable[[list[str]], int]] = {
    "rebase-open-branches": rebase_open_branches.main,
    "changelog-fragments": changelog_fragments.main,
    "check-submodule-pins": check_submodule_pins.main,
    "status-report": status_report.main,
    "roadmap-order": roadmap_order.main,
    "close-merged-issue": close_merged_issue.main,
    "fetch-docs": fetch_docs.main,
    "container": container_cli.main,
}


def split_log_directory_option(arguments: Sequence[str]) -> tuple[Path, list[str]]:
    """
    A leading `--log-directory DIR` → (DIR, the rest); without it, the default directory.
    """
    if arguments and arguments[0] == LOG_DIRECTORY_FLAG:
        if len(arguments) < 2:
            raise CommandLineUsageError(f"{LOG_DIRECTORY_FLAG} needs a directory")
        return Path(arguments[1]), list(arguments[2:])
    return Path(DEFAULT_LOG_DIRECTORY), list(arguments)


def split_run_arguments(run_arguments: Sequence[str]) -> tuple[str, list[str]]:
    """
    `["build", "--", "make", "-j"]` → ("build", ["make", "-j"]). The `--` is optional.
    """
    if not run_arguments:
        raise CommandLineUsageError("run needs a log name and a command")
    log_name, command = run_arguments[0], list(run_arguments[1:])
    if not re.fullmatch(LOG_NAME_PATTERN, log_name):
        raise CommandLineUsageError(
            f"log name may use only letters, digits, '.', '_', '-', got: {log_name}"
        )
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        raise CommandLineUsageError(f"run {log_name} needs a command")
    return log_name, command


def prune_run_log_files(log_directory: Path, older_than_days: int, run_log: RunLog) -> int:
    """
    Remove the selected run logs and report how many bytes that freed.
    """
    selected_paths = select_run_log_files_to_remove(
        log_directory, Path(run_log.log_file.name), older_than_days, get_current_utc_time()
    )
    total_freed_bytes = 0
    for selected_path in selected_paths:
        freed_bytes = selected_path.stat().st_size
        try:
            selected_path.unlink()
        except OSError as remove_error:
            run_log.write_line("err", f"could not remove {selected_path}: {remove_error}")
            return EXIT_CODE_SETUP_ERROR
        total_freed_bytes += freed_bytes
    age_text = "" if older_than_days == 0 else f" older than {older_than_days} days"
    run_log.write_line(
        "run", f"removed {len(selected_paths)} run logs{age_text}: {total_freed_bytes} bytes"
    )
    return 0


def build_run_body(
    subcommand: str, extra_arguments: Sequence[str], log_directory: Path
) -> tuple[str, Callable[[RunLog], int]]:
    """
    (log name, body) for a subcommand, or CommandLineUsageError before any log is opened.
    """
    if subcommand == "run":
        log_name, command = split_run_arguments(extra_arguments)
        return log_name, functools.partial(run_command_with_timestamped_output, command)
    if subcommand == "prune-logs":
        try:
            older_than_days = parse_older_than_days_argument(extra_arguments)
        except RunLogCleanupUsageError as usage_error:
            raise CommandLineUsageError(str(usage_error)) from usage_error
        return "prune-logs", functools.partial(prune_run_log_files, log_directory, older_than_days)
    raise CommandLineUsageError(f"unknown subcommand: {subcommand}")


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] in ("-h", "--help"):
        print(USAGE_TEXT)
        return 0
    if arguments and arguments[0] in REPOSITORY_WORKFLOW_SUBCOMMANDS:
        return REPOSITORY_WORKFLOW_SUBCOMMANDS[arguments[0]](arguments[1:])
    try:
        log_directory, remaining_arguments = split_log_directory_option(arguments)
        if not remaining_arguments:
            raise CommandLineUsageError("no subcommand given")
        subcommand, extra_arguments = remaining_arguments[0], remaining_arguments[1:]
        log_name, run_body = build_run_body(subcommand, extra_arguments, log_directory)
    except CommandLineUsageError as usage_error:
        print(f"devops-tools: {usage_error}\n\n{USAGE_TEXT}", file=sys.stderr)
        return EXIT_CODE_USAGE_ERROR
    return run_with_run_log(log_directory, log_name, ["devops-tools", *arguments], run_body)


if __name__ == "__main__":
    sys.exit(main())
