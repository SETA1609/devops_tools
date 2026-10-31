"""
Timestamped terminal output and one log file per CLI run.
Every line a child process prints is prefixed with an ISO-8601 UTC timestamp
(milliseconds) and a stream tag, then written to the terminal and the run log.
Tags: `out` (child stdout), `err` (child stderr or a tool error), `run` (tool
bookkeeping: command lines, exit codes, durations).
"""

from __future__ import annotations

import datetime
import shlex
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import IO, TextIO

from devops_tools.constants import (
    EXIT_CODE_PROGRAM_NOT_FOUND,
    EXIT_CODE_SIGNAL_BASE,
)

UtcClock = Callable[[], datetime.datetime]


def get_current_utc_time() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


def format_utc_timestamp(moment: datetime.datetime) -> str:
    """
    `2026-10-19T15:02:18.111Z`: UTC, millisecond precision, truncated.
    """
    moment_utc = moment.astimezone(datetime.UTC)
    return moment_utc.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def prefix_line_with_utc_timestamp(line: str, stream_tag: str, moment: datetime.datetime) -> str:
    return f"{format_utc_timestamp(moment)} {stream_tag} | {line}"


def build_run_log_file_name(subcommand: str, moment: datetime.datetime) -> str:
    """
    `20261019T150218.111Z-build.log`: sorts by start time, no characters that need quoting.
    """
    moment_utc = moment.astimezone(datetime.UTC)
    milliseconds = moment_utc.microsecond // 1000
    return f"{moment_utc:%Y%m%dT%H%M%S}.{milliseconds:03d}Z-{subcommand}.log"


def open_run_log_file(log_directory: Path, subcommand: str, moment: datetime.datetime) -> TextIO:
    """
    Create a new log file. Runs started in the same millisecond get `-2`, `-3`… suffixes.
    """
    log_directory.mkdir(parents=True, exist_ok=True)
    file_name = build_run_log_file_name(subcommand, moment)
    stem = file_name.removesuffix(".log")
    attempt_number = 1
    while True:
        candidate_path = log_directory / file_name
        try:
            return candidate_path.open("x", encoding="utf-8")
        except FileExistsError:
            attempt_number += 1
            file_name = f"{stem}-{attempt_number}.log"


class RunLog:
    """
    Writes timestamped lines to the terminal and the log file. Safe to call from threads.
    """

    def __init__(
        self,
        log_file: TextIO,
        terminal_out: TextIO,
        terminal_err: TextIO,
        clock: UtcClock = get_current_utc_time,
    ) -> None:
        self.log_file = log_file
        self.terminal_out = terminal_out
        self.terminal_err = terminal_err
        self.clock = clock
        self.write_lock = threading.Lock()

    def write_line(self, stream_tag: str, text: str) -> None:
        """
        Write `text` as one or more lines; each line inside it gets its own prefix.
        """
        moment = self.clock()
        prefixed_lines = "".join(
            prefix_line_with_utc_timestamp(line, stream_tag, moment) + "\n"
            for line in text.split("\n")
        )
        terminal = self.terminal_out if stream_tag == "out" else self.terminal_err
        with self.write_lock:
            terminal.write(prefixed_lines)
            terminal.flush()
            self.log_file.write(prefixed_lines)
            self.log_file.flush()


def decode_output_line(raw_line: bytes) -> str:
    line_without_newline = raw_line.removesuffix(b"\n").removesuffix(b"\r")
    return line_without_newline.decode("utf-8", errors="replace")


def copy_stream_lines_to_run_log(stream: IO[bytes], stream_tag: str, run_log: RunLog) -> None:
    for raw_line in iter(stream.readline, b""):
        run_log.write_line(stream_tag, decode_output_line(raw_line))
    stream.close()


def convert_return_code_to_exit_code(return_code: int) -> int:
    """
    A child killed by signal N reports -N; shells report that as 128 + N.
    """
    if return_code < 0:
        return EXIT_CODE_SIGNAL_BASE - return_code
    return return_code


def wait_for_process_through_interrupts(process: subprocess.Popen[bytes]) -> int:
    """
    Ctrl-C also reaches the child (same process group); wait for it to stop.
    A second Ctrl-C kills the child.
    """
    interrupt_count = 0
    while True:
        try:
            return process.wait()
        except KeyboardInterrupt:
            interrupt_count += 1
            if interrupt_count >= 2:
                process.kill()


def run_command_with_timestamped_output(command: Sequence[str], run_log: RunLog) -> int:
    """
    Run `command`, timestamp and log each output line, return its exit code.
    """
    run_log.write_line("run", f"command: {shlex.join(command)}")
    start_seconds = time.monotonic()
    try:
        process = subprocess.Popen(
            list(command),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError:
        run_log.write_line("err", f"program not found: {command[0]}")
        exit_code = EXIT_CODE_PROGRAM_NOT_FOUND
    else:
        assert process.stdout is not None and process.stderr is not None
        stream_copy_threads = [
            threading.Thread(
                target=copy_stream_lines_to_run_log, args=(process.stdout, "out", run_log)
            ),
            threading.Thread(
                target=copy_stream_lines_to_run_log, args=(process.stderr, "err", run_log)
            ),
        ]
        for stream_copy_thread in stream_copy_threads:
            stream_copy_thread.start()
        return_code = wait_for_process_through_interrupts(process)
        for stream_copy_thread in stream_copy_threads:
            stream_copy_thread.join()
        exit_code = convert_return_code_to_exit_code(return_code)
    duration_seconds = time.monotonic() - start_seconds
    run_log.write_line("run", f"exit code: {exit_code}, duration: {duration_seconds:.3f} s")
    return exit_code


def run_with_run_log(
    log_directory: Path,
    log_name: str,
    command_line: Sequence[str],
    run_body: Callable[[RunLog], int],
    terminal_out: TextIO | None = None,
    terminal_err: TextIO | None = None,
    clock: UtcClock = get_current_utc_time,
) -> int:
    """
    Open a new run log named after `log_name`, run `run_body` with it, and return its exit code.
    The log starts with its own path and ends with `command_line`, the exit code, and the
    duration of the whole run.
    """
    start_seconds = time.monotonic()
    with open_run_log_file(log_directory, log_name, clock()) as log_file:
        run_log = RunLog(
            log_file,
            terminal_out if terminal_out is not None else sys.stdout,
            terminal_err if terminal_err is not None else sys.stderr,
            clock,
        )
        run_log.write_line("run", f"log: {log_file.name}")
        exit_code = run_body(run_log)
        duration_seconds = time.monotonic() - start_seconds
        run_log.write_line("run", f"finished: {shlex.join(command_line)}")
        run_log.write_line("run", f"exit code: {exit_code}, duration: {duration_seconds:.3f} s")
    return exit_code
