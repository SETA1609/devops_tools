import datetime
import io
import sys

from devops_tools.run_log import (
    RunLog,
    build_run_log_file_name,
    format_utc_timestamp,
    open_run_log_file,
    prefix_line_with_utc_timestamp,
    run_command_with_timestamped_output,
)

FIXED_MOMENT = datetime.datetime(2026, 10, 19, 15, 2, 18, 111_999, tzinfo=datetime.UTC)


def get_fixed_moment() -> datetime.datetime:
    return FIXED_MOMENT


def create_run_log_in_memory() -> tuple[RunLog, io.StringIO, io.StringIO, io.StringIO]:
    log_file = io.StringIO()
    terminal_out = io.StringIO()
    terminal_err = io.StringIO()
    run_log = RunLog(log_file, terminal_out, terminal_err, clock=get_fixed_moment)
    return run_log, log_file, terminal_out, terminal_err


def test_format_utc_timestamp_uses_milliseconds_and_z_suffix():
    assert format_utc_timestamp(FIXED_MOMENT) == "2026-10-19T15:02:18.111Z"


def test_format_utc_timestamp_converts_other_timezones_to_utc():
    two_hours_east = datetime.timezone(datetime.timedelta(hours=2))
    moment = datetime.datetime(2026, 10, 19, 17, 2, 18, 111_000, tzinfo=two_hours_east)
    assert format_utc_timestamp(moment) == "2026-10-19T15:02:18.111Z"


def test_prefix_line_with_utc_timestamp_puts_timestamp_and_stream_tag_first():
    prefixed = prefix_line_with_utc_timestamp("Build Summary: 3/3 steps", "out", FIXED_MOMENT)
    assert prefixed == "2026-10-19T15:02:18.111Z out | Build Summary: 3/3 steps"


def test_build_run_log_file_name_is_sortable_and_names_the_subcommand():
    assert build_run_log_file_name("test", FIXED_MOMENT) == "20261019T150218.111Z-test.log"


def test_open_run_log_file_creates_the_log_directory(tmp_path):
    log_directory = tmp_path / "cache" / "logs"
    with open_run_log_file(log_directory, "build", FIXED_MOMENT) as log_file:
        log_file.write("line\n")
    assert (log_directory / "20261019T150218.111Z-build.log").read_text() == "line\n"


def test_open_run_log_file_never_overwrites_a_log_from_the_same_millisecond(tmp_path):
    with open_run_log_file(tmp_path, "build", FIXED_MOMENT) as first_log_file:
        first_log_file.write("first\n")
    with open_run_log_file(tmp_path, "build", FIXED_MOMENT) as second_log_file:
        second_log_file.write("second\n")
    assert (tmp_path / "20261019T150218.111Z-build.log").read_text() == "first\n"
    assert (tmp_path / "20261019T150218.111Z-build-2.log").read_text() == "second\n"


def test_run_log_writes_out_lines_to_stdout_and_err_lines_to_stderr():
    run_log, log_file, terminal_out, terminal_err = create_run_log_in_memory()
    run_log.write_line("out", "compiled")
    run_log.write_line("err", "warning")
    assert terminal_out.getvalue() == "2026-10-19T15:02:18.111Z out | compiled\n"
    assert terminal_err.getvalue() == "2026-10-19T15:02:18.111Z err | warning\n"
    assert log_file.getvalue() == (
        "2026-10-19T15:02:18.111Z out | compiled\n2026-10-19T15:02:18.111Z err | warning\n"
    )


def test_run_command_with_timestamped_output_timestamps_every_line_of_both_streams():
    run_log, log_file, _, _ = create_run_log_in_memory()
    child_script = (
        "import sys\n"
        "print('first out')\n"
        "print('second out')\n"
        "sys.stdout.flush()\n"
        "print('only err', file=sys.stderr)\n"
        "sys.stdout.write('no trailing newline')\n"
    )
    exit_code = run_command_with_timestamped_output([sys.executable, "-c", child_script], run_log)
    assert exit_code == 0
    log_lines = log_file.getvalue().splitlines()
    assert all(line.startswith("2026-10-19T15:02:18.111Z ") for line in log_lines)
    assert "2026-10-19T15:02:18.111Z out | first out" in log_lines
    assert "2026-10-19T15:02:18.111Z out | second out" in log_lines
    assert "2026-10-19T15:02:18.111Z err | only err" in log_lines
    assert "2026-10-19T15:02:18.111Z out | no trailing newline" in log_lines


def test_run_command_with_timestamped_output_returns_the_child_exit_code():
    run_log, log_file, _, _ = create_run_log_in_memory()
    exit_code = run_command_with_timestamped_output(
        [sys.executable, "-c", "raise SystemExit(3)"], run_log
    )
    assert exit_code == 3
    assert (
        log_file.getvalue()
        .splitlines()[-1]
        .startswith("2026-10-19T15:02:18.111Z run | exit code: 3, duration: ")
    )


def test_run_command_with_timestamped_output_records_the_command_line_first():
    run_log, log_file, _, _ = create_run_log_in_memory()
    run_command_with_timestamped_output([sys.executable, "-c", "pass"], run_log)
    first_line = log_file.getvalue().splitlines()[0]
    assert first_line.startswith("2026-10-19T15:02:18.111Z run | command: ")
    assert first_line.endswith(" -c pass")


def test_run_command_with_timestamped_output_returns_127_for_a_missing_program():
    run_log, log_file, _, _ = create_run_log_in_memory()
    exit_code = run_command_with_timestamped_output(["devops-tools-test-no-such-program"], run_log)
    assert exit_code == 127
    assert "err | program not found: devops-tools-test-no-such-program" in log_file.getvalue()


def test_run_command_with_timestamped_output_keeps_invalid_utf8_lines():
    run_log, log_file, _, _ = create_run_log_in_memory()
    child_script = "import sys; sys.stdout.buffer.write(b'bad \\xff byte\\n')"
    run_command_with_timestamped_output([sys.executable, "-c", child_script], run_log)
    assert "out | bad � byte" in log_file.getvalue()


def test_run_log_prefixes_every_line_of_multi_line_text():
    run_log, log_file, _, _ = create_run_log_in_memory()
    run_log.write_line("run", "command: python -c 'first\nsecond'")
    assert log_file.getvalue() == (
        "2026-10-19T15:02:18.111Z run | command: python -c 'first\n"
        "2026-10-19T15:02:18.111Z run | second'\n"
    )
