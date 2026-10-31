import datetime
import os

import pytest

from devops_tools.exceptions import RunLogCleanupUsageError
from devops_tools.run_log_cleanup import (
    parse_older_than_days_argument,
    select_run_log_files_to_remove,
)

CURRENT_MOMENT = datetime.datetime(2026, 10, 29, 12, 0, 0, tzinfo=datetime.UTC)


def write_run_log_aged_days(log_directory, file_name, age_days):
    log_path = log_directory / file_name
    log_path.write_text("2026-10-29T12:00:00.000Z run | exit code: 0\n")
    modified_timestamp_seconds = CURRENT_MOMENT.timestamp() - age_days * 86_400
    os.utime(log_path, (modified_timestamp_seconds, modified_timestamp_seconds))
    return log_path


@pytest.mark.parametrize(
    ("extra_arguments", "expected_days"),
    [([], 0), (["--older-than-days", "7"], 7), (["--older-than-days", "0"], 0)],
)
def test_parse_older_than_days_argument_accepts_nothing_or_the_flag(extra_arguments, expected_days):
    assert parse_older_than_days_argument(extra_arguments) == expected_days


@pytest.mark.parametrize(
    ("extra_arguments", "expected_message"),
    [
        (["--older-than-days"], "takes only"),
        (["7"], "takes only"),
        (["--older-than-days", "seven"], "whole number"),
        (["--older-than-days", "-1"], "cannot be negative"),
    ],
)
def test_parse_older_than_days_argument_rejects_bad_usage(extra_arguments, expected_message):
    with pytest.raises(RunLogCleanupUsageError, match=expected_message):
        parse_older_than_days_argument(extra_arguments)


def test_select_run_log_files_to_remove_takes_every_log_except_the_current_run(tmp_path):
    old_log_path = write_run_log_aged_days(tmp_path, "20261019T150801.950Z-lint.log", 10)
    new_log_path = write_run_log_aged_days(tmp_path, "20261029T110000.000Z-test.log", 0)
    current_log_path = write_run_log_aged_days(tmp_path, "20261029T120000.000Z-prune-logs.log", 0)
    selected_paths = select_run_log_files_to_remove(tmp_path, current_log_path, 0, CURRENT_MOMENT)
    assert selected_paths == [old_log_path, new_log_path]


def test_select_run_log_files_to_remove_keeps_logs_newer_than_the_cutoff(tmp_path):
    old_log_path = write_run_log_aged_days(tmp_path, "20261019T150801.950Z-lint.log", 10)
    write_run_log_aged_days(tmp_path, "20261027T090000.000Z-build.log", 2)
    selected_paths = select_run_log_files_to_remove(tmp_path, None, 7, CURRENT_MOMENT)
    assert selected_paths == [old_log_path]


def test_select_run_log_files_to_remove_leaves_other_files_directories_and_symlinks(tmp_path):
    write_run_log_aged_days(tmp_path, "session-recap.md", 10)
    (tmp_path / "nested.log").mkdir()
    target_log_path = write_run_log_aged_days(tmp_path / "nested.log", "inside.log", 10)
    (tmp_path / "linked.log").symlink_to(target_log_path)
    assert select_run_log_files_to_remove(tmp_path, None, 0, CURRENT_MOMENT) == []


def test_select_run_log_files_to_remove_returns_nothing_without_a_log_directory(tmp_path):
    missing_directory = tmp_path / "cache" / "logs"
    assert select_run_log_files_to_remove(missing_directory, None, 0, CURRENT_MOMENT) == []
