import sys

import pytest

from devops_tools.cli import main, split_log_directory_option, split_run_arguments
from devops_tools.exceptions import CommandLineUsageError


def read_only_run_log(log_directory):
    (log_path,) = sorted(log_directory.glob("*.log"))
    return log_path, log_path.read_text().splitlines()


def test_split_log_directory_option_defaults_to_cache_logs():
    log_directory, remaining_arguments = split_log_directory_option(["prune-logs"])
    assert str(log_directory) == "cache/logs"
    assert remaining_arguments == ["prune-logs"]


def test_split_log_directory_option_takes_a_leading_directory():
    log_directory, remaining_arguments = split_log_directory_option(
        ["--log-directory", "logs", "run", "build", "make"]
    )
    assert str(log_directory) == "logs"
    assert remaining_arguments == ["run", "build", "make"]


@pytest.mark.parametrize(
    ("run_arguments", "expected"),
    [
        (["build", "make", "-j"], ("build", ["make", "-j"])),
        (["build", "--", "make", "--", "x"], ("build", ["make", "--", "x"])),
    ],
)
def test_split_run_arguments_accepts_an_optional_double_dash(run_arguments, expected):
    assert split_run_arguments(run_arguments) == expected


@pytest.mark.parametrize(
    ("run_arguments", "expected_message"),
    [
        ([], "needs a log name"),
        (["build"], "needs a command"),
        (["build", "--"], "needs a command"),
        (["../escape", "make"], "log name may use only"),
    ],
)
def test_split_run_arguments_rejects_bad_usage(run_arguments, expected_message):
    with pytest.raises(CommandLineUsageError, match=expected_message):
        split_run_arguments(run_arguments)


def test_main_run_logs_the_command_and_returns_its_exit_code(tmp_path, capsys):
    exit_code = main(
        [
            "--log-directory",
            str(tmp_path),
            "run",
            "check",
            "--",
            sys.executable,
            "-c",
            "print('hello'); raise SystemExit(4)",
        ]
    )
    assert exit_code == 4
    log_path, log_lines = read_only_run_log(tmp_path)
    assert log_path.name.endswith("-check.log")
    assert log_lines[0].endswith(f"run | log: {log_path}")
    assert any(line.endswith("out | hello") for line in log_lines)
    assert " run | finished: devops-tools --log-directory " in log_lines[-2]
    assert " run | exit code: 4, duration: " in log_lines[-1]
    assert "out | hello" in capsys.readouterr().out


def test_main_prune_logs_keeps_only_its_own_log(tmp_path):
    (tmp_path / "20261019T150218.111Z-build.log").write_text("old\n")
    (tmp_path / "notes.md").write_text("kept\n")
    exit_code = main(["--log-directory", str(tmp_path), "prune-logs"])
    assert exit_code == 0
    log_path, log_lines = read_only_run_log(tmp_path)
    assert log_path.name.endswith("-prune-logs.log")
    assert any("removed 1 run logs: 4 bytes" in line for line in log_lines)
    assert (tmp_path / "notes.md").exists()


@pytest.mark.parametrize(
    "arguments",
    [
        [],
        ["--log-directory"],
        ["unknown"],
        ["run", "build"],
        ["prune-logs", "--older-than-days", "seven"],
    ],
)
def test_main_reports_usage_errors_without_writing_a_log(tmp_path, capsys, arguments):
    exit_code = main(["--log-directory", str(tmp_path), *arguments] if arguments else arguments)
    assert exit_code == 2
    assert "usage: devops-tools" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []


def test_main_help_prints_usage_and_succeeds(capsys):
    assert main(["--help"]) == 0
    assert "run <name>" in capsys.readouterr().out


@pytest.mark.parametrize(
    "subcommand", ["rebase-open-branches", "changelog-fragments", "check-submodule-pins"]
)
def test_main_passes_repository_workflow_subcommands_through(subcommand, capsys):
    with pytest.raises(SystemExit) as exit_info:
        main([subcommand, "--help"])
    assert exit_info.value.code == 0
    assert f"devops-tools {subcommand}" in capsys.readouterr().out


def test_main_runs_a_repository_workflow_subcommand_without_a_log(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "changes").mkdir()
    assert main(["changelog-fragments", "--repository", str(tmp_path), "check"]) == 0
    assert "Changelog fragments are valid." in capsys.readouterr().out
    assert not (tmp_path / "cache").exists()
