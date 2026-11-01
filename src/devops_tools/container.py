"""
The toolchain container: finding the checkout and the runtime, checking the toolchain version,
and building docker/podman command lines from `[tool.devops-tools.container]`.
The checkout is mounted at its host path, and so is its git directory when that lives outside
(a worktree or a submodule), so git works inside the container from any checkout.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import importlib.resources
import json
import os
import re
import shutil
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

from devops_tools.constants import (
    AGENT_HOME_VOLUME_ENVIRONMENT_VARIABLE,
    AGENT_IMAGE_DIRECTORY_NAME,
    AGENT_IMAGE_OVERRIDE_ENVIRONMENT_VARIABLE,
    AGENT_IMAGE_SUFFIX,
    AGENT_SETUP_COMMANDS_ENVIRONMENT_VARIABLE,
    BASE_IMAGE_BUILD_ARGUMENT,
    BASE_IMAGE_DIRECTORY_NAME,
    BASE_IMAGE_REPOSITORY,
    CONTAINER_AGENT_HOME_DIRECTORY,
    CONTAINER_KEPT_CACHE_MOUNT,
    CONTENT_HASH_LENGTH,
    DEFAULT_IMAGE_TAG_WITHOUT_VERSION,
    DOCKERFILE_BASE_IMAGE_ARGUMENT_LINE,
    DOCKERFILE_FROM_BASE_IMAGE_LINE,
    IMAGE_OVERRIDE_ENVIRONMENT_VARIABLE,
    KEEP_CACHE_FLAG,
    REBUILD_AGENT_IMAGE_FLAG,
    RUN_AS_ROOT_ENVIRONMENT_VARIABLE,
    SHIPPED_DOCKERFILE_NAME,
    SHIPPED_IMAGES_DIRECTORY_NAME,
    SUPPORTED_CONTAINER_BINARIES,
)
from devops_tools.exceptions import ContainerSetupError
from devops_tools.models import ContainerRunSettings, ContainerSettings


def run_git_quietly(directory: Path, *arguments: str) -> str | None:
    """
    stdout of `git -C directory ...` without its newline, or None when git fails or is missing.
    """
    try:
        completed = subprocess.run(
            ["git", "-C", str(directory), *arguments],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return None
    return completed.stdout.strip() if completed.returncode == 0 else None


def find_repository_root(start_directory: Path) -> Path:
    """
    The top of the git checkout holding `start_directory` (a worktree is its own top), or
    `start_directory` itself outside git.
    """
    top_level = run_git_quietly(start_directory, "rev-parse", "--show-toplevel")
    return Path(top_level) if top_level else start_directory.resolve()


def find_git_common_directory_outside(repository_root: Path) -> Path | None:
    """
    The shared git directory when it lies outside the checkout, as for a worktree or a
    submodule, whose `.git` file points there. None when it is inside or there is no git.
    """
    common_directory = run_git_quietly(
        repository_root, "rev-parse", "--path-format=absolute", "--git-common-dir"
    )
    if common_directory is None:
        return None
    common_path = Path(common_directory).resolve()
    if common_path.is_relative_to(repository_root.resolve()):
        return None
    return common_path


def read_toolchain_version(
    repository_root: Path, container_settings: ContainerSettings
) -> str | None:
    """
    The version in `version-file`, after checking that the Dockerfile's `ARG <version-argument>=`
    and every `version-pins` file name the same one. None when no version file is configured.
    """
    if container_settings.version_file is None or container_settings.version_argument is None:
        return None
    version_path = repository_root / container_settings.version_file
    try:
        pinned_version = version_path.read_text(encoding="utf-8").strip()
    except OSError as read_error:
        raise ContainerSetupError(f"cannot read {version_path}: {read_error}") from read_error
    argument_pattern = rf"^ARG {re.escape(container_settings.version_argument)}=(\S+)\s*$"
    pins = [(container_settings.dockerfile, argument_pattern)] + [
        (version_pin.file, version_pin.pattern) for version_pin in container_settings.version_pins
    ]
    for pin_file, pin_pattern in pins:
        pin_path = repository_root / pin_file
        try:
            pin_text = pin_path.read_text(encoding="utf-8")
        except OSError as read_error:
            raise ContainerSetupError(f"cannot read {pin_path}: {read_error}") from read_error
        pin_match = re.search(pin_pattern, pin_text, re.MULTILINE)
        if pin_match is None:
            raise ContainerSetupError(f"{pin_path} does not match {pin_pattern!r}")
        if pin_match.group(1) != pinned_version:
            raise ContainerSetupError(
                f"{container_settings.version_file} is {pinned_version} but {pin_path} "
                f"pins {pin_match.group(1)}"
            )
    return pinned_version


def get_shipped_images_directory(image_directory_name: str = BASE_IMAGE_DIRECTORY_NAME) -> Path:
    """
    The directory in the installed package holding one shared image's Dockerfile and files:
    `base` (default) or `agent`.
    """
    shipped_images = importlib.resources.files("devops_tools") / SHIPPED_IMAGES_DIRECTORY_NAME
    return Path(str(shipped_images / image_directory_name))


def compute_shipped_image_tag(images_directory: Path, image_repository: str) -> str:
    """
    `<repository>:<package version>-<content hash>`: the hash covers every file in the shipped
    images directory, so a changed Dockerfile gets a new tag and is rebuilt.
    """
    try:
        package_version = importlib.metadata.version("devops-tools")
    except importlib.metadata.PackageNotFoundError:
        package_version = "0"
    content_hash = hashlib.sha256()
    for file_path in sorted(path for path in images_directory.iterdir() if path.is_file()):
        content_hash.update(file_path.name.encode("utf-8") + b"\0" + file_path.read_bytes())
    return f"{image_repository}:{package_version}-{content_hash.hexdigest()[:CONTENT_HASH_LENGTH]}"


def compute_base_image_tag(images_directory: Path) -> str:
    return compute_shipped_image_tag(images_directory, BASE_IMAGE_REPOSITORY)


def build_base_image_build_arguments(
    container_binary: str, images_directory: Path, base_image: str
) -> list[str]:
    return [
        container_binary, "build",
        "--file", str(images_directory / SHIPPED_DOCKERFILE_NAME),
        "--tag", base_image,
        str(images_directory),
    ]  # fmt: skip


def check_dockerfile_builds_on_base_image(
    repository_root: Path, container_settings: ContainerSettings
) -> None:
    """
    The project Dockerfile must declare `ARG BASE_IMAGE` and build a stage `FROM ${BASE_IMAGE}`,
    so every project image carries the shared tooling and adds only its own toolchain.
    """
    dockerfile_path = repository_root / container_settings.dockerfile
    try:
        dockerfile_text = dockerfile_path.read_text(encoding="utf-8")
    except OSError as read_error:
        raise ContainerSetupError(f"cannot read {dockerfile_path}: {read_error}") from read_error
    if not DOCKERFILE_BASE_IMAGE_ARGUMENT_LINE.search(
        dockerfile_text
    ) or not DOCKERFILE_FROM_BASE_IMAGE_LINE.search(dockerfile_text):
        raise ContainerSetupError(
            f"{dockerfile_path} must build on the devops-tools base image: declare "
            "`ARG BASE_IMAGE` before the first FROM and build a stage `FROM ${BASE_IMAGE}`"
        )


def build_image_tag(container_settings: ContainerSettings, toolchain_version: str | None) -> str:
    """
    `<image>:<toolchain>-<version>`, or `<image>:latest` without a version. `IMAGE` overrides.
    """
    override_image = os.environ.get(IMAGE_OVERRIDE_ENVIRONMENT_VARIABLE)
    if override_image:
        return override_image
    if toolchain_version is None:
        return f"{container_settings.image}:{DEFAULT_IMAGE_TAG_WITHOUT_VERSION}"
    return f"{container_settings.image}:{container_settings.toolchain}-{toolchain_version}"


def is_container_daemon_reachable(container_binary: str) -> bool:
    if shutil.which(container_binary) is None:
        return False
    info_result = subprocess.run(
        [container_binary, "info"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return info_result.returncode == 0


def detect_container_binary(
    check_daemon_reachable: Callable[[str], bool] = is_container_daemon_reachable,
) -> str:
    """
    Docker if its daemon answers, else podman.
    """
    for container_binary in SUPPORTED_CONTAINER_BINARIES:
        if check_daemon_reachable(container_binary):
            return container_binary
    raise ContainerSetupError("docker or podman is required and the daemon must be running")


def get_host_user_and_group_ids() -> tuple[int, int] | None:
    """
    Run as the host user so files in the checkout stay theirs. `CONTAINER_AS_ROOT=1` opts out.
    """
    if os.environ.get(RUN_AS_ROOT_ENVIRONMENT_VARIABLE):
        return None
    return (os.getuid(), os.getgid())


def does_container_object_exist(container_binary: str, object_kind: str, object_name: str) -> bool:
    """
    `<binary> <image|volume> inspect <name>` succeeds.
    """
    inspect_result = subprocess.run(
        [container_binary, object_kind, "inspect", object_name],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return inspect_result.returncode == 0


def resolve_read_only_mount_paths(
    repository_root: Path, container_settings: ContainerSettings
) -> tuple[Path, ...]:
    """
    For each `read-only-symlink-mounts` entry that is a symlink to an existing directory or
    file, its resolved target, mounted read-only at that same path so the symlink resolves
    inside the container. Missing or dangling entries are skipped.
    """
    mount_paths: list[Path] = []
    for symlink_path_text in container_settings.read_only_symlink_mounts:
        symlink_path = repository_root / symlink_path_text
        if not symlink_path.is_symlink():
            continue
        target_path = symlink_path.resolve()
        if target_path.exists() and target_path not in mount_paths:
            mount_paths.append(target_path)
    return tuple(mount_paths)


def build_image_build_arguments(
    container_binary: str,
    repository_root: Path,
    container_settings: ContainerSettings,
    image: str,
    toolchain_version: str | None,
    base_image: str,
) -> list[str]:
    version_arguments: list[str] = []
    if toolchain_version is not None and container_settings.version_argument is not None:
        version_arguments = [
            "--build-arg", f"{container_settings.version_argument}={toolchain_version}"
        ]  # fmt: skip
    return [
        container_binary, "build",
        "--file", str(repository_root / container_settings.dockerfile),
        "--build-arg", f"{BASE_IMAGE_BUILD_ARGUMENT}={base_image}",
        *version_arguments,
        "--tag", image,
        str(repository_root),
    ]  # fmt: skip


def build_prune_dangling_images_arguments(container_binary: str) -> list[str]:
    return [container_binary, "image", "prune", "-f"]


def build_prune_build_cache_arguments(container_binary: str) -> list[str]:
    return [container_binary, "builder", "prune", "-f"]


def build_image_summary_arguments(container_binary: str, image: str) -> list[str]:
    return [container_binary, "image", "inspect", image, "--format", "id={{.Id}} size={{.Size}}"]


def build_checkout_mount_arguments(run_settings: ContainerRunSettings) -> list[str]:
    """
    The checkout and its outside git directory at their host paths, read-only mounts, and
    `safe.directory` for the checkout, so git accepts it even when the container runs as root.
    """
    checkout_path = str(run_settings.repository_root)
    mount_arguments = ["-v", f"{checkout_path}:{checkout_path}"]
    if run_settings.git_common_directory is not None:
        git_path = str(run_settings.git_common_directory)
        mount_arguments += ["-v", f"{git_path}:{git_path}"]
    for read_only_path in run_settings.read_only_mount_paths:
        mount_arguments += ["-v", f"{read_only_path}:{read_only_path}:ro"]
    return [
        *mount_arguments,
        "-e", "GIT_CONFIG_COUNT=1",
        "-e", "GIT_CONFIG_KEY_0=safe.directory",
        "-e", f"GIT_CONFIG_VALUE_0={checkout_path}",
        "-w", checkout_path,
    ]  # fmt: skip


def build_cache_arguments(container_settings: ContainerSettings, keep_cache: bool) -> list[str]:
    """
    The cache variable at `<home>/cache` (thrown away with the container), or with
    `keep_cache` at the mounted cache volume.
    """
    variable_name = container_settings.cache_environment_variable
    if variable_name is None:
        return []
    if keep_cache and container_settings.cache_volume is not None:
        return [
            "-e", f"{variable_name}={CONTAINER_KEPT_CACHE_MOUNT}",
            "-v", f"{container_settings.cache_volume}:{CONTAINER_KEPT_CACHE_MOUNT}",
        ]  # fmt: skip
    return ["-e", f"{variable_name}={container_settings.home_directory}/cache"]


def build_container_run_arguments(
    run_settings: ContainerRunSettings,
    container_settings: ContainerSettings,
    command_in_container: Sequence[str],
    keep_stdin_open: bool = False,
    allocate_terminal: bool = False,
) -> list[str]:
    """
    `<binary> run --rm` of the toolchain image with a throwaway home: nothing outside the
    checkout is kept, except the cache volume with `keep_cache`.
    """
    user_arguments: list[str] = []
    if run_settings.user_and_group_ids is not None:
        user_id, group_id = run_settings.user_and_group_ids
        user_arguments = ["--user", f"{user_id}:{group_id}"]
    terminal_arguments = (["-i"] if keep_stdin_open else []) + (["-t"] if allocate_terminal else [])
    return [
        run_settings.container_binary, "run", "--rm",
        *terminal_arguments,
        *user_arguments,
        "-e", f"HOME={container_settings.home_directory}",
        *build_cache_arguments(container_settings, run_settings.keep_cache),
        *build_checkout_mount_arguments(run_settings),
        run_settings.image,
        *command_in_container,
    ]  # fmt: skip


def split_keep_cache_flag(extra_arguments: Sequence[str]) -> tuple[bool, list[str]]:
    """
    Take leading `--keep-cache` flags off the arguments; everything after goes to the command.
    Only a leading flag counts, so `tool run x -- --keep-cache` still reaches the program.
    """
    remaining_arguments = list(extra_arguments)
    keep_cache = False
    while remaining_arguments and remaining_arguments[0] == KEEP_CACHE_FLAG:
        keep_cache = True
        remaining_arguments.pop(0)
    return keep_cache, remaining_arguments


def build_volume_create_arguments(container_binary: str, volume_name: str) -> list[str]:
    return [container_binary, "volume", "create", volume_name]


def build_volume_remove_arguments(container_binary: str, volume_name: str) -> list[str]:
    return [container_binary, "volume", "rm", volume_name]


def build_volume_chown_arguments(
    container_binary: str, image: str, volume_name: str, user_and_group_ids: tuple[int, int]
) -> list[str]:
    """
    A new volume is root-owned; hand it to the host user once, as root, so tools can write.
    """
    user_id, group_id = user_and_group_ids
    return [
        container_binary, "run", "--rm",
        "--user", "0:0",
        "-v", f"{volume_name}:{CONTAINER_KEPT_CACHE_MOUNT}",
        "--entrypoint", "chown",
        image,
        f"{user_id}:{group_id}", CONTAINER_KEPT_CACHE_MOUNT,
    ]  # fmt: skip


def build_volume_size_arguments(container_binary: str, image: str, volume_name: str) -> list[str]:
    """
    `du -sb` over the volume; prints `<bytes>\t<path>`.
    """
    return [
        container_binary, "run", "--rm",
        "-v", f"{volume_name}:{CONTAINER_KEPT_CACHE_MOUNT}",
        "--entrypoint", "du",
        image,
        "-sb", CONTAINER_KEPT_CACHE_MOUNT,
    ]  # fmt: skip


def measure_volume_size_bytes(container_binary: str, image: str, volume_name: str) -> int | None:
    """
    Bytes in the volume, or None when it cannot be measured (no image, no volume).
    """
    size_result = subprocess.run(
        build_volume_size_arguments(container_binary, image, volume_name),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
    )
    if size_result.returncode != 0:
        return None
    try:
        return int(size_result.stdout.split()[0])
    except (IndexError, ValueError):
        return None


def build_agent_image_tag(project_image: str) -> str:
    """
    `<project repository>-agent:<project tag>-<agent content hash>`, so a changed agent
    Dockerfile or start script gets a new tag. `AGENT_IMAGE` overrides.
    """
    override_image = os.environ.get(AGENT_IMAGE_OVERRIDE_ENVIRONMENT_VARIABLE)
    if override_image:
        return override_image
    project_repository, _, project_tag = project_image.rpartition(":")
    shipped_tag = compute_shipped_image_tag(
        get_shipped_images_directory(AGENT_IMAGE_DIRECTORY_NAME), "agent"
    )
    content_hash = shipped_tag.rsplit("-", 1)[-1]
    return f"{project_repository}{AGENT_IMAGE_SUFFIX}:{project_tag}-{content_hash}"


def get_agent_home_volume_name(container_settings: ContainerSettings) -> str:
    return (
        os.environ.get(AGENT_HOME_VOLUME_ENVIRONMENT_VARIABLE)
        or container_settings.agent_home_volume
    )


def build_agent_image_build_arguments(
    container_binary: str,
    images_directory: Path,
    agent_image: str,
    project_image: str,
    user_and_group_ids: tuple[int, int],
    claude_code_version: str | None,
) -> list[str]:
    """
    Build the shipped agent image on the project image, with the agent user at the host's ids.
    """
    user_id, group_id = user_and_group_ids
    version_arguments = (
        ["--build-arg", f"CLAUDE_CODE_VERSION={claude_code_version}"] if claude_code_version else []
    )
    return [
        container_binary, "build",
        "--file", str(images_directory / SHIPPED_DOCKERFILE_NAME),
        "--build-arg", f"{BASE_IMAGE_BUILD_ARGUMENT}={project_image}",
        "--build-arg", f"AGENT_USER_ID={user_id}",
        "--build-arg", f"AGENT_GROUP_ID={group_id}",
        *version_arguments,
        "--tag", agent_image,
        str(images_directory),
    ]  # fmt: skip


def build_agent_container_run_arguments(
    run_settings: ContainerRunSettings,
    container_settings: ContainerSettings,
    home_volume_name: str,
    agent_command: Sequence[str],
    allocate_terminal: bool,
) -> list[str]:
    """
    `<binary> run --rm -i` of the agent image. The image's own user has the host's ids, so no
    `--user`; the home is the named volume; the start script gets the setup commands as JSON.
    """
    podman_arguments = ["--userns=keep-id"] if run_settings.container_binary == "podman" else []
    setup_commands_json = json.dumps(
        [list(command) for command in container_settings.agent_setup_commands]
    )
    return [
        run_settings.container_binary, "run", "--rm", "-i",
        *(["-t"] if allocate_terminal else []),
        *podman_arguments,
        "-v", f"{home_volume_name}:{CONTAINER_AGENT_HOME_DIRECTORY}",
        "-e", f"{AGENT_SETUP_COMMANDS_ENVIRONMENT_VARIABLE}={setup_commands_json}",
        *build_cache_arguments(container_settings, run_settings.keep_cache),
        *build_checkout_mount_arguments(run_settings),
        run_settings.image,
        *agent_command,
    ]  # fmt: skip


def split_agent_leading_flags(extra_arguments: Sequence[str]) -> tuple[bool, bool, list[str]]:
    """
    (keep_cache, rebuild_agent_image, command): leading `--keep-cache` and `--rebuild-image`
    in any order. Flags after the command are the command's.
    """
    remaining_arguments = list(extra_arguments)
    keep_cache = False
    rebuild_agent_image = False
    while remaining_arguments and remaining_arguments[0] in (
        KEEP_CACHE_FLAG,
        REBUILD_AGENT_IMAGE_FLAG,
    ):
        if remaining_arguments.pop(0) == KEEP_CACHE_FLAG:
            keep_cache = True
        else:
            rebuild_agent_image = True
    return keep_cache, rebuild_agent_image, remaining_arguments
