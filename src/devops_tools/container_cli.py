"""
`devops-tools container [--repository PATH] [--settings-file PATH] <action> [args...]`:
run the project's toolchain container as `[tool.devops-tools.container]` describes it.
Every run writes `<repository>/cache/logs/<utc-timestamp>-<action>.log`.
    image                      build the image, prune dangling layers, print its id and size
    <command> [--keep-cache] [args...]
                               a command named in [tool.devops-tools.container.commands]
    exec [--keep-cache] [--] <command> [args...]
                               any command in the container
    shell [--keep-cache]       an interactive bash in the container
    prune                      remove dangling images and unused build cache
    clean                      end of work only: clean-directories, the cache volume, prune
"""

from __future__ import annotations

import argparse
import functools
import shlex
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from devops_tools.constants import (
    DEFAULT_LOG_DIRECTORY,
    EXIT_CODE_SETUP_ERROR,
    EXIT_CODE_USAGE_ERROR,
    KEEP_CACHE_FLAG,
)
from devops_tools.container import (
    build_container_run_arguments,
    build_image_build_arguments,
    build_image_summary_arguments,
    build_image_tag,
    build_prune_build_cache_arguments,
    build_prune_dangling_images_arguments,
    build_volume_chown_arguments,
    build_volume_create_arguments,
    build_volume_remove_arguments,
    detect_container_binary,
    does_container_object_exist,
    find_git_common_directory_outside,
    find_repository_root,
    get_host_user_and_group_ids,
    measure_volume_size_bytes,
    read_toolchain_version,
    resolve_read_only_mount_paths,
    split_keep_cache_flag,
)
from devops_tools.container_cleanup import (
    measure_directory_size_bytes,
    remove_directory_tree,
    select_paths_to_remove,
)
from devops_tools.exceptions import (
    CleanupRefusedError,
    CommandLineUsageError,
    ContainerSetupError,
    RepositorySettingsError,
)
from devops_tools.models import ContainerRunSettings, ContainerSettings
from devops_tools.run_log import RunLog, run_command_with_timestamped_output, run_with_run_log
from devops_tools.settings import read_repository_settings

ContainerActionFunction = Callable[[Path, ContainerSettings, list[str], RunLog], int]


def build_container_image(
    repository_root: Path,
    container_settings: ContainerSettings,
    container_binary: str,
    run_log: RunLog,
) -> int:
    toolchain_version = read_toolchain_version(repository_root, container_settings)
    image = build_image_tag(container_settings, toolchain_version)
    version_text = (
        ""
        if toolchain_version is None
        else f" ({container_settings.toolchain} {toolchain_version})"
    )
    run_log.write_line("run", f"building {image}{version_text}")
    return run_command_with_timestamped_output(
        build_image_build_arguments(
            container_binary, repository_root, container_settings, image, toolchain_version
        ),
        run_log,
    )


def build_container_image_if_missing(
    repository_root: Path,
    container_settings: ContainerSettings,
    container_binary: str,
    run_log: RunLog,
) -> int:
    toolchain_version = read_toolchain_version(repository_root, container_settings)
    image = build_image_tag(container_settings, toolchain_version)
    if does_container_object_exist(container_binary, "image", image):
        return 0
    return build_container_image(repository_root, container_settings, container_binary, run_log)


def prepare_kept_cache_volume(
    container_settings: ContainerSettings, container_binary: str, image: str, run_log: RunLog
) -> int:
    """
    Create the cache volume on first use and hand it to the host user. Reuse it after.
    """
    volume_name = container_settings.cache_volume
    if volume_name is None:
        run_log.write_line("err", f"{KEEP_CACHE_FLAG} needs cache-volume in the settings")
        return EXIT_CODE_USAGE_ERROR
    if does_container_object_exist(container_binary, "volume", volume_name):
        run_log.write_line("run", f"cache: reusing volume {volume_name}")
        return 0
    run_log.write_line("run", f"cache: creating volume {volume_name}")
    create_exit_code = run_command_with_timestamped_output(
        build_volume_create_arguments(container_binary, volume_name), run_log
    )
    user_and_group_ids = get_host_user_and_group_ids()
    if create_exit_code != 0 or user_and_group_ids is None:
        return create_exit_code
    return run_command_with_timestamped_output(
        build_volume_chown_arguments(container_binary, image, volume_name, user_and_group_ids),
        run_log,
    )


def prepare_container_run(
    repository_root: Path, container_settings: ContainerSettings, keep_cache: bool, run_log: RunLog
) -> tuple[ContainerRunSettings, int]:
    """
    Find the runtime, build the image if missing, set up the cache. Return (settings, code).
    """
    container_binary = detect_container_binary()
    image = build_image_tag(
        container_settings, read_toolchain_version(repository_root, container_settings)
    )
    run_settings = ContainerRunSettings(
        container_binary=container_binary,
        repository_root=repository_root,
        image=image,
        user_and_group_ids=get_host_user_and_group_ids(),
        git_common_directory=find_git_common_directory_outside(repository_root),
        read_only_mount_paths=resolve_read_only_mount_paths(repository_root, container_settings),
        keep_cache=keep_cache,
    )
    image_exit_code = build_container_image_if_missing(
        repository_root, container_settings, container_binary, run_log
    )
    if image_exit_code != 0 or container_settings.cache_environment_variable is None:
        return run_settings, image_exit_code
    if not keep_cache:
        run_log.write_line("run", f"cache: throwaway (pass {KEEP_CACHE_FLAG} to keep it)")
        return run_settings, 0
    return run_settings, prepare_kept_cache_volume(
        container_settings, container_binary, image, run_log
    )


def run_command_in_container(
    repository_root: Path,
    container_settings: ContainerSettings,
    command_in_container: Sequence[str],
    keep_cache: bool,
    run_log: RunLog,
) -> int:
    run_settings, setup_exit_code = prepare_container_run(
        repository_root, container_settings, keep_cache, run_log
    )
    if setup_exit_code != 0:
        return setup_exit_code
    return run_command_with_timestamped_output(
        build_container_run_arguments(run_settings, container_settings, command_in_container),
        run_log,
    )


def prune_container_images_and_build_cache(container_binary: str, run_log: RunLog) -> int:
    """
    Remove dangling images and unused build cache. Tagged images and volumes stay.
    """
    run_log.write_line("run", "pruning dangling images and unused build cache")
    for prune_arguments in (
        build_prune_dangling_images_arguments(container_binary),
        build_prune_build_cache_arguments(container_binary),
    ):
        prune_exit_code = run_command_with_timestamped_output(prune_arguments, run_log)
        if prune_exit_code != 0:
            return prune_exit_code
    return 0


def run_image_action(
    repository_root: Path,
    container_settings: ContainerSettings,
    action_arguments: list[str],
    run_log: RunLog,
) -> int:
    """
    Build the image, prune dangling layers and build cache, print the image id and size.
    """
    container_binary = detect_container_binary()
    build_exit_code = build_container_image(
        repository_root, container_settings, container_binary, run_log
    )
    if build_exit_code != 0:
        return build_exit_code
    prune_exit_code = prune_container_images_and_build_cache(container_binary, run_log)
    if prune_exit_code != 0:
        return prune_exit_code
    image = build_image_tag(
        container_settings, read_toolchain_version(repository_root, container_settings)
    )
    run_log.write_line("run", f"{image} is ready")
    return run_command_with_timestamped_output(
        build_image_summary_arguments(container_binary, image), run_log
    )


def run_exec_action(
    repository_root: Path,
    container_settings: ContainerSettings,
    action_arguments: list[str],
    run_log: RunLog,
) -> int:
    keep_cache, command_in_container = split_keep_cache_flag(action_arguments)
    if command_in_container and command_in_container[0] == "--":
        command_in_container = command_in_container[1:]
    if not command_in_container:
        run_log.write_line("err", "exec needs a command")
        return EXIT_CODE_USAGE_ERROR
    return run_command_in_container(
        repository_root, container_settings, command_in_container, keep_cache, run_log
    )


def run_named_command_action(
    named_command: Sequence[str],
    repository_root: Path,
    container_settings: ContainerSettings,
    action_arguments: list[str],
    run_log: RunLog,
) -> int:
    keep_cache, extra_arguments = split_keep_cache_flag(action_arguments)
    return run_command_in_container(
        repository_root, container_settings, [*named_command, *extra_arguments], keep_cache, run_log
    )


def open_interactive_container_shell(
    repository_root: Path,
    container_settings: ContainerSettings,
    action_arguments: list[str],
    run_log: RunLog,
) -> int:
    """
    Interactive bash in the container. It owns the terminal, so only start and end are logged.
    """
    keep_cache, shell_arguments = split_keep_cache_flag(action_arguments)
    if shell_arguments:
        run_log.write_line(
            "err", f"shell takes only {KEEP_CACHE_FLAG}, got: {shlex.join(shell_arguments)}"
        )
        return EXIT_CODE_USAGE_ERROR
    run_settings, setup_exit_code = prepare_container_run(
        repository_root, container_settings, keep_cache, run_log
    )
    if setup_exit_code != 0:
        return setup_exit_code
    shell_command = build_container_run_arguments(
        run_settings,
        container_settings,
        ["bash"],
        keep_stdin_open=True,
        allocate_terminal=sys.stdin.isatty(),
    )
    run_log.write_line("run", f"shell started: {shlex.join(shell_command)}")
    shell_result = subprocess.run(shell_command, check=False)
    run_log.write_line("run", f"shell ended, exit code: {shell_result.returncode}")
    return shell_result.returncode


def run_prune_action(
    repository_root: Path,
    container_settings: ContainerSettings,
    action_arguments: list[str],
    run_log: RunLog,
) -> int:
    return prune_container_images_and_build_cache(detect_container_binary(), run_log)


def run_clean_action(
    repository_root: Path,
    container_settings: ContainerSettings,
    action_arguments: list[str],
    run_log: RunLog,
) -> int:
    """
    End-of-work cleanup: `clean-directories`, the cache volume, then prune.
    Runs only when a person asks or says the work is finished. Nothing else calls it.
    """
    try:
        selected_paths = select_paths_to_remove(
            repository_root,
            [repository_root / directory for directory in container_settings.clean_directories],
            container_settings.protected_directories,
        )
    except CleanupRefusedError as refused_error:
        run_log.write_line("err", str(refused_error))
        return EXIT_CODE_SETUP_ERROR
    total_freed_bytes = 0
    for selected_path in selected_paths:
        freed_bytes = measure_directory_size_bytes(selected_path)
        try:
            remove_directory_tree(selected_path)
        except OSError as remove_error:
            run_log.write_line("err", f"could not remove {selected_path}: {remove_error}")
            return EXIT_CODE_SETUP_ERROR
        total_freed_bytes += freed_bytes
        relative_path = selected_path.relative_to(repository_root.resolve())
        run_log.write_line("run", f"removed {relative_path}/: {freed_bytes} bytes")
    container_binary = detect_container_binary()
    volume_name = container_settings.cache_volume
    if volume_name is not None and does_container_object_exist(
        container_binary, "volume", volume_name
    ):
        image = build_image_tag(
            container_settings, read_toolchain_version(repository_root, container_settings)
        )
        volume_bytes = measure_volume_size_bytes(container_binary, image, volume_name)
        remove_exit_code = run_command_with_timestamped_output(
            build_volume_remove_arguments(container_binary, volume_name), run_log
        )
        if remove_exit_code != 0:
            return remove_exit_code
        volume_size_text = "size unknown" if volume_bytes is None else f"{volume_bytes} bytes"
        total_freed_bytes += volume_bytes or 0
        run_log.write_line("run", f"removed volume {volume_name}: {volume_size_text}")
    elif volume_name is not None:
        run_log.write_line("run", f"volume {volume_name} is not present")
    prune_exit_code = prune_container_images_and_build_cache(container_binary, run_log)
    run_log.write_line("run", f"freed {total_freed_bytes} bytes")
    return prune_exit_code


BUILT_IN_ACTIONS_WITHOUT_ARGUMENTS: dict[str, ContainerActionFunction] = {
    "image": run_image_action,
    "prune": run_prune_action,
    "clean": run_clean_action,
}
BUILT_IN_ACTIONS_WITH_ARGUMENTS: dict[str, ContainerActionFunction] = {
    "exec": run_exec_action,
    "shell": open_interactive_container_shell,
}


def find_container_action(
    action_name: str, action_arguments: list[str], container_settings: ContainerSettings
) -> ContainerActionFunction:
    """
    The function for a built-in action or a named command, or CommandLineUsageError.
    """
    if action_name in BUILT_IN_ACTIONS_WITHOUT_ARGUMENTS:
        if action_arguments:
            raise CommandLineUsageError(
                f"{action_name} takes no arguments, got: {shlex.join(action_arguments)}"
            )
        return BUILT_IN_ACTIONS_WITHOUT_ARGUMENTS[action_name]
    if action_name in BUILT_IN_ACTIONS_WITH_ARGUMENTS:
        return BUILT_IN_ACTIONS_WITH_ARGUMENTS[action_name]
    named_commands = dict(container_settings.commands)
    if action_name in named_commands:
        return functools.partial(run_named_command_action, named_commands[action_name])
    known_actions = [
        *BUILT_IN_ACTIONS_WITHOUT_ARGUMENTS,
        *BUILT_IN_ACTIONS_WITH_ARGUMENTS,
        *named_commands,
    ]
    raise CommandLineUsageError(
        f"unknown container action {action_name!r}; known: {', '.join(sorted(known_actions))}"
    )


def parse_container_arguments(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="devops-tools container",
        description="Run the project's toolchain container.",
        epilog=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--repository", type=Path, help="Checkout to use (default: git top level)")
    parser.add_argument(
        "--settings-file",
        type=Path,
        help="pyproject.toml with [tool.devops-tools.container] (default: the repository's own)",
    )
    parser.add_argument("action", help="image, exec, shell, prune, clean, or a named command")
    parser.add_argument("action_arguments", nargs=argparse.REMAINDER)
    return parser.parse_args(list(argv))


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    parsed_arguments = parse_container_arguments(arguments)
    repository_root = (
        parsed_arguments.repository.resolve()
        if parsed_arguments.repository is not None
        else find_repository_root(Path.cwd())
    )
    try:
        settings = read_repository_settings(repository_root, parsed_arguments.settings_file)
        if settings.container is None:
            raise RepositorySettingsError(
                "no [tool.devops-tools.container] table in the settings file"
            )
        action_function = find_container_action(
            parsed_arguments.action, parsed_arguments.action_arguments, settings.container
        )
    except (RepositorySettingsError, CommandLineUsageError) as usage_error:
        print(f"devops-tools container: {usage_error}", file=sys.stderr)
        return EXIT_CODE_USAGE_ERROR
    container_settings = settings.container

    def run_action_with_setup_errors_logged(run_log: RunLog) -> int:
        try:
            return action_function(
                repository_root, container_settings, parsed_arguments.action_arguments, run_log
            )
        except ContainerSetupError as setup_error:
            run_log.write_line("err", str(setup_error))
            return EXIT_CODE_SETUP_ERROR

    return run_with_run_log(
        repository_root / DEFAULT_LOG_DIRECTORY,
        parsed_arguments.action,
        ["devops-tools", "container", *arguments],
        run_action_with_setup_errors_logged,
    )


if __name__ == "__main__":
    sys.exit(main())
