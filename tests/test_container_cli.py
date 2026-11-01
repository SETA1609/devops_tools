"""
`devops-tools container` against a fake docker on PATH that records every call.
"""

import os
import stat
from pathlib import Path

import pytest

from devops_tools.container_cli import main

FAKE_DOCKER_SCRIPT = """#!/bin/sh
printf '%s\\n' "$*" >> "$FAKE_DOCKER_CALLS"
case "$1 $2" in
    "image inspect") exit "${FAKE_IMAGE_EXIT_CODE:-0}" ;;
    "volume inspect") exit "${FAKE_VOLUME_EXIT_CODE:-0}" ;;
esac
exit 0
"""

PROJECT_SETTINGS = """
[tool.devops-tools.container]
image = "example"
toolchain = "tool"
version-file = ".tool-version"
version-argument = "TOOL_VERSION"
cache-environment-variable = "TOOL_CACHE_DIR"
cache-volume = "example-cache"
clean-directories = ["build-output"]

[tool.devops-tools.container.commands]
build = ["tool", "build"]
"""


@pytest.fixture
def checkout(tmp_path, monkeypatch):
    """
    A checkout with settings, a version pin, and a fake docker first on PATH.
    """
    repository_root = tmp_path / "checkout"
    (repository_root / "container").mkdir(parents=True)
    (repository_root / "pyproject.toml").write_text(PROJECT_SETTINGS)
    (repository_root / ".tool-version").write_text("1.2.3\n")
    (repository_root / "container" / "Dockerfile").write_text("ARG TOOL_VERSION=1.2.3\n")
    fake_binary_directory = tmp_path / "bin"
    fake_binary_directory.mkdir()
    fake_docker_path = fake_binary_directory / "docker"
    fake_docker_path.write_text(FAKE_DOCKER_SCRIPT)
    fake_docker_path.chmod(fake_docker_path.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{fake_binary_directory}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_DOCKER_CALLS", str(tmp_path / "docker-calls.txt"))
    monkeypatch.delenv("IMAGE", raising=False)
    monkeypatch.delenv("CONTAINER_AS_ROOT", raising=False)
    return repository_root


def read_docker_calls(repository_root: Path) -> list[str]:
    calls_path = repository_root.parent / "docker-calls.txt"
    return calls_path.read_text().splitlines() if calls_path.exists() else []


def run_container(repository_root: Path, *arguments: str) -> int:
    return main(["--repository", str(repository_root), *arguments])


def test_a_named_command_builds_a_missing_image_and_keeps_the_cache(checkout, monkeypatch):
    """
    What: a named command from [tool.devops-tools.container.commands].
    When: the image and the cache volume are missing and `--keep-cache` comes first.
    Then: the image is built with the version argument, the volume is created and handed to
    the host user, and the command runs with its extra arguments at the checkout's host path.
    """
    monkeypatch.setenv("FAKE_IMAGE_EXIT_CODE", "1")
    monkeypatch.setenv("FAKE_VOLUME_EXIT_CODE", "1")
    assert run_container(checkout, "build", "--keep-cache", "-Drelease") == 0
    docker_calls = read_docker_calls(checkout)
    assert any(
        call.startswith("build --file") and "TOOL_VERSION=1.2.3 --tag example:tool-1.2.3" in call
        for call in docker_calls
    )
    assert "volume create example-cache" in docker_calls
    assert any("--entrypoint chown" in call for call in docker_calls)
    run_call = docker_calls[-1]
    assert run_call.startswith("run --rm --user ")
    assert f"-w {checkout} example:tool-1.2.3 tool build -Drelease" in run_call
    assert "-e TOOL_CACHE_DIR=/kept-cache" in run_call
    (log_path,) = (checkout / "cache" / "logs").glob("*-build.log")
    assert "exit code: 0" in log_path.read_text().splitlines()[-1]


def test_exec_runs_any_command_without_rebuilding_a_present_image(checkout):
    """
    What: the exec action.
    When: the image exists and the command follows `--`.
    Then: no build happens and the command runs with a throwaway cache.
    """
    assert run_container(checkout, "exec", "--", "tool", "version") == 0
    docker_calls = read_docker_calls(checkout)
    assert not any(call.startswith("build ") for call in docker_calls)
    assert docker_calls[-1].endswith("example:tool-1.2.3 tool version")
    assert "-e TOOL_CACHE_DIR=/tmp/container-home/cache" in docker_calls[-1]


def test_clean_removes_build_directories_and_the_cache_volume(checkout):
    """
    What: the clean action.
    When: a clean directory and the cache volume exist.
    Then: the directory is removed, the volume is removed, and images are pruned.
    """
    (checkout / "build-output").mkdir()
    (checkout / "build-output" / "artifact.bin").write_bytes(b"1234")
    assert run_container(checkout, "clean") == 0
    assert not (checkout / "build-output").exists()
    docker_calls = read_docker_calls(checkout)
    assert "volume rm example-cache" in docker_calls
    assert "image prune -f" in docker_calls
    assert "builder prune -f" in docker_calls


@pytest.mark.parametrize(
    ("arguments", "expected_message"),
    [
        (["unknown"], "unknown container action 'unknown'; known: build, clean, exec"),
        (["image", "extra"], "image takes no arguments"),
    ],
)
def test_usage_errors_stop_before_any_log_or_docker_call(
    checkout, capsys, arguments, expected_message
):
    """
    What: the container CLI.
    When: the action is unknown or a built-in action gets arguments.
    Then: it exits 2 with a message, writes no log, and never calls docker.
    """
    assert run_container(checkout, *arguments) == 2
    assert expected_message in capsys.readouterr().err
    assert not (checkout / "cache").exists()
    assert read_docker_calls(checkout) == []


def test_exec_without_a_command_is_a_logged_usage_error(checkout):
    """
    What: the exec action.
    When: no command follows it.
    Then: it exits 2 and the run log says a command is needed.
    """
    assert run_container(checkout, "exec", "--") == 2
    (log_path,) = (checkout / "cache" / "logs").glob("*-exec.log")
    assert "exec needs a command" in log_path.read_text()


def test_a_checkout_without_a_container_table_is_a_usage_error(tmp_path, capsys):
    """
    What: the container CLI.
    When: the settings have no [tool.devops-tools.container] table.
    Then: it exits 2 and says the table is missing.
    """
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    assert main(["--repository", str(tmp_path), "image"]) == 2
    assert "no [tool.devops-tools.container] table" in capsys.readouterr().err


def test_a_version_mismatch_is_logged_as_a_setup_error(checkout):
    """
    What: the container CLI.
    When: the Dockerfile pins another toolchain version than the version file.
    Then: it exits 1 and the run log names both versions.
    """
    (checkout / "container" / "Dockerfile").write_text("ARG TOOL_VERSION=9.9.9\n")
    assert run_container(checkout, "build") == 1
    (log_path,) = (checkout / "cache" / "logs").glob("*-build.log")
    assert "1.2.3 but" in log_path.read_text()
