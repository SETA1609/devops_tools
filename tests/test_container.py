import subprocess
from pathlib import Path

import pytest

from devops_tools.container import (
    build_agent_image_tag,
    build_base_image_build_arguments,
    build_container_run_arguments,
    build_image_build_arguments,
    build_image_tag,
    check_dockerfile_builds_on_base_image,
    compute_base_image_tag,
    detect_container_binary,
    find_git_common_directory_outside,
    find_repository_root,
    get_shipped_images_directory,
    read_toolchain_version,
    resolve_read_only_mount_paths,
    split_agent_leading_flags,
    split_keep_cache_flag,
)
from devops_tools.container_cleanup import select_paths_to_remove
from devops_tools.exceptions import CleanupRefusedError, ContainerSetupError
from devops_tools.models import ContainerRunSettings, ContainerSettings, VersionPin

VERSIONED_SETTINGS = ContainerSettings(
    image="example",
    toolchain="zig",
    version_file=".tool-version",
    version_argument="TOOL_VERSION",
    cache_environment_variable="TOOL_CACHE_DIR",
    cache_volume="example-cache",
)


def write_versioned_checkout(repository_root: Path, dockerfile_version: str = "1.2.3") -> None:
    (repository_root / "container").mkdir(parents=True, exist_ok=True)
    (repository_root / ".tool-version").write_text("1.2.3\n")
    (repository_root / "container" / "Dockerfile").write_text(
        f"FROM scratch\nARG TOOL_VERSION={dockerfile_version}\n"
    )


def create_run_settings(repository_root: Path, **overrides) -> ContainerRunSettings:
    values = {
        "container_binary": "docker",
        "repository_root": repository_root,
        "image": "example:zig-1.2.3",
        "user_and_group_ids": (1000, 1000),
        "git_common_directory": None,
        "read_only_mount_paths": (),
        "keep_cache": False,
    }
    values.update(overrides)
    return ContainerRunSettings(**values)


def git(directory: Path, *arguments: str) -> None:
    subprocess.run(["git", "-C", str(directory), *arguments], check=True, capture_output=True)


def test_read_toolchain_version_returns_the_pinned_version(tmp_path):
    """
    What: read_toolchain_version.
    When: the version file and the Dockerfile's ARG name the same version.
    Then: it returns that version.
    """
    write_versioned_checkout(tmp_path)
    assert read_toolchain_version(tmp_path, VERSIONED_SETTINGS) == "1.2.3"


def test_read_toolchain_version_rejects_a_dockerfile_with_another_version(tmp_path):
    """
    What: read_toolchain_version.
    When: the Dockerfile's ARG pins a different version than the version file.
    Then: it fails and names both versions.
    """
    write_versioned_checkout(tmp_path, dockerfile_version="9.9.9")
    with pytest.raises(ContainerSetupError, match=r"1\.2\.3 but .* pins 9\.9\.9"):
        read_toolchain_version(tmp_path, VERSIONED_SETTINGS)


def test_read_toolchain_version_checks_every_version_pin(tmp_path):
    """
    What: read_toolchain_version.
    When: a version-pins file names another version.
    Then: it fails and names that file.
    """
    write_versioned_checkout(tmp_path)
    (tmp_path / "devcontainer.json").write_text('{"BASE_IMAGE": "example:zig-1.0.0"}')
    settings = ContainerSettings(
        image="example",
        version_file=".tool-version",
        version_argument="TOOL_VERSION",
        version_pins=(VersionPin(file="devcontainer.json", pattern=r"example:zig-([0-9.]+)"),),
    )
    with pytest.raises(ContainerSetupError, match=r"devcontainer\.json pins 1\.0\.0"):
        read_toolchain_version(tmp_path, settings)


def test_read_toolchain_version_without_a_version_file_is_none(tmp_path):
    """
    What: read_toolchain_version.
    When: the settings name no version file.
    Then: it returns None without reading anything.
    """
    assert read_toolchain_version(tmp_path, ContainerSettings(image="example")) is None


@pytest.mark.parametrize(
    ("toolchain_version", "image_override", "expected_tag"),
    [
        ("1.2.3", None, "example:zig-1.2.3"),
        (None, None, "example:latest"),
        ("1.2.3", "mine:dev", "mine:dev"),
    ],
)
def test_build_image_tag(monkeypatch, toolchain_version, image_override, expected_tag):
    """
    What: build_image_tag.
    When: a version is known or not, and IMAGE is set or not.
    Then: the tag is `<image>:<toolchain>-<version>`, `<image>:latest`, or IMAGE itself.
    """
    if image_override is None:
        monkeypatch.delenv("IMAGE", raising=False)
    else:
        monkeypatch.setenv("IMAGE", image_override)
    assert build_image_tag(VERSIONED_SETTINGS, toolchain_version) == expected_tag


def test_build_image_build_arguments_pass_the_version_build_argument(tmp_path):
    """
    What: build_image_build_arguments.
    When: a toolchain version is known.
    Then: the build gets the base image and `<version-argument>=<version>` as build arguments,
    and the configured Dockerfile.
    """
    assert build_image_build_arguments(
        "docker", tmp_path, VERSIONED_SETTINGS, "example:zig-1.2.3", "1.2.3", "base:1"
    ) == [
        "docker", "build",
        "--file", str(tmp_path / "container/Dockerfile"),
        "--build-arg", "BASE_IMAGE=base:1",
        "--build-arg", "TOOL_VERSION=1.2.3",
        "--tag", "example:zig-1.2.3",
        str(tmp_path),
    ]  # fmt: skip


def test_build_container_run_arguments_mount_the_checkout_at_its_host_path(tmp_path):
    """
    What: build_container_run_arguments.
    When: a command runs with a throwaway cache.
    Then: the checkout is mounted and used at its host path, git trusts it, the host user runs
    the command, and the cache variable points into the throwaway home.
    """
    arguments = build_container_run_arguments(
        create_run_settings(tmp_path), VERSIONED_SETTINGS, ["tool", "build"]
    )
    assert arguments == [
        "docker", "run", "--rm",
        "--user", "1000:1000",
        "-e", "HOME=/tmp/container-home",
        "-e", "TOOL_CACHE_DIR=/tmp/container-home/cache",
        "-v", f"{tmp_path}:{tmp_path}",
        "-e", "GIT_CONFIG_COUNT=1",
        "-e", "GIT_CONFIG_KEY_0=safe.directory",
        "-e", f"GIT_CONFIG_VALUE_0={tmp_path}",
        "-w", str(tmp_path),
        "example:zig-1.2.3",
        "tool", "build",
    ]  # fmt: skip


def test_build_container_run_arguments_mount_the_kept_cache_and_extra_paths(tmp_path):
    """
    What: build_container_run_arguments.
    When: the cache is kept, the git directory is outside the checkout, and a read-only path
    is mounted.
    Then: the cache volume, the git directory, and the read-only path are mounted.
    """
    git_directory = tmp_path / "main" / ".git"
    data_directory = tmp_path / "data"
    arguments = build_container_run_arguments(
        create_run_settings(
            tmp_path / "worktree",
            keep_cache=True,
            git_common_directory=git_directory,
            read_only_mount_paths=(data_directory,),
            user_and_group_ids=None,
        ),
        VERSIONED_SETTINGS,
        ["bash"],
        keep_stdin_open=True,
        allocate_terminal=True,
    )
    command_line = " ".join(arguments)
    assert arguments[:5] == ["docker", "run", "--rm", "-i", "-t"]
    assert "--user" not in arguments
    assert "-e TOOL_CACHE_DIR=/kept-cache -v example-cache:/kept-cache" in command_line
    assert f"-v {git_directory}:{git_directory}" in command_line
    assert f"-v {data_directory}:{data_directory}:ro" in command_line


def test_find_git_common_directory_outside_is_the_main_git_directory_for_a_worktree(tmp_path):
    """
    What: find_repository_root and find_git_common_directory_outside.
    When: they run in a linked worktree and in the main checkout.
    Then: the worktree is its own root and gets the main .git; the main checkout gets None.
    """
    main_checkout = tmp_path / "main"
    main_checkout.mkdir()
    git(main_checkout, "init", "-q", "-b", "main")
    git(
        main_checkout,
        "-c",
        "user.name=T",
        "-c",
        "user.email=t@e",
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "start",
    )
    git(main_checkout, "worktree", "add", "-q", str(tmp_path / "linked"), "-b", "feature")
    linked_root = find_repository_root(tmp_path / "linked")
    assert linked_root == (tmp_path / "linked").resolve()
    assert find_git_common_directory_outside(linked_root) == (main_checkout / ".git").resolve()
    assert find_git_common_directory_outside(main_checkout.resolve()) is None


def test_resolve_read_only_mount_paths_follows_symlinks_and_skips_the_rest(tmp_path):
    """
    What: resolve_read_only_mount_paths.
    When: the list holds a symlink to a directory, a dangling symlink, and a plain directory.
    Then: only the symlink's resolved target is mounted.
    """
    (tmp_path / "outside-data").mkdir()
    (tmp_path / "references").mkdir()
    (tmp_path / "references" / "data").symlink_to(tmp_path / "outside-data")
    (tmp_path / "references" / "gone").symlink_to(tmp_path / "missing")
    (tmp_path / "references" / "plain").mkdir()
    settings = ContainerSettings(
        image="example",
        read_only_symlink_mounts=("references/data", "references/gone", "references/plain"),
    )
    assert resolve_read_only_mount_paths(tmp_path, settings) == (
        (tmp_path / "outside-data").resolve(),
    )


@pytest.mark.parametrize(
    ("extra_arguments", "expected"),
    [
        (["--keep-cache", "-Dx"], (True, ["-Dx"])),
        (["-Dx", "--keep-cache"], (False, ["-Dx", "--keep-cache"])),
        ([], (False, [])),
    ],
)
def test_split_keep_cache_flag_takes_only_leading_flags(extra_arguments, expected):
    """
    What: split_keep_cache_flag.
    When: `--keep-cache` comes first, later, or not at all.
    Then: only a leading flag turns the kept cache on; later ones reach the command.
    """
    assert split_keep_cache_flag(extra_arguments) == expected


def test_detect_container_binary_prefers_docker_then_podman():
    """
    What: detect_container_binary.
    When: docker's daemon does not answer but podman's does, and when neither does.
    Then: it picks podman, and with neither it fails.
    """
    assert detect_container_binary(lambda binary: binary == "podman") == "podman"
    with pytest.raises(ContainerSetupError, match="docker or podman"):
        detect_container_binary(lambda binary: False)


def test_select_paths_to_remove_takes_existing_directories_in_order(tmp_path):
    """
    What: select_paths_to_remove.
    When: one configured directory exists and one does not.
    Then: only the existing one is selected.
    """
    (tmp_path / "build-output").mkdir()
    selected_paths = select_paths_to_remove(
        tmp_path, [tmp_path / "build-output", tmp_path / ".build-cache"], ["cache/logs"]
    )
    assert selected_paths == [(tmp_path / "build-output").resolve()]


@pytest.mark.parametrize(
    ("candidate_relative_path", "expected_message"),
    [
        ("cache/logs", "never cleaned"),
        ("..", "not inside"),
        (".", "not inside"),
        ("linked", "symlink"),
    ],
)
def test_select_paths_to_remove_refuses_unsafe_paths(
    tmp_path, candidate_relative_path, expected_message
):
    """
    What: select_paths_to_remove.
    When: a candidate is protected, outside the checkout, the checkout itself, or a symlink.
    Then: the whole selection is refused with a message naming the reason.
    """
    (tmp_path / "cache" / "logs").mkdir(parents=True)
    (tmp_path / "linked").symlink_to(tmp_path / "cache")
    with pytest.raises(CleanupRefusedError, match=expected_message):
        select_paths_to_remove(tmp_path, [tmp_path / candidate_relative_path], ["cache/logs"])


def test_the_package_ships_the_base_image_files():
    """
    What: get_shipped_images_directory.
    When: the package is installed.
    Then: it holds the base Dockerfile and the entrypoint, and the Dockerfile adds no toolchain
    beyond Python, uv, and git.
    """
    images_directory = get_shipped_images_directory()
    base_dockerfile_text = (images_directory / "Dockerfile").read_text()
    assert (images_directory / "entrypoint.sh").is_file()
    assert "uv python install" in base_dockerfile_text
    assert "ENTRYPOINT" in base_dockerfile_text
    for toolchain_word in ("zig", "clang", "openjdk", "golang"):
        assert toolchain_word not in base_dockerfile_text.lower()


def test_compute_base_image_tag_changes_with_the_shipped_files(tmp_path):
    """
    What: compute_base_image_tag.
    When: a file in the images directory changes.
    Then: the tag keeps its repository and version but gets a new content hash.
    """
    (tmp_path / "Dockerfile").write_text("FROM scratch\n")
    first_tag = compute_base_image_tag(tmp_path)
    (tmp_path / "Dockerfile").write_text("FROM scratch\nRUN true\n")
    second_tag = compute_base_image_tag(tmp_path)
    assert first_tag.startswith("devops-tools-base:")
    assert first_tag.rsplit("-", 1)[0] == second_tag.rsplit("-", 1)[0]
    assert first_tag != second_tag


def test_build_base_image_build_arguments_use_the_shipped_directory_as_context(tmp_path):
    """
    What: build_base_image_build_arguments.
    When: the base image is built.
    Then: the shipped directory is the build context and holds the Dockerfile.
    """
    assert build_base_image_build_arguments("podman", tmp_path, "devops-tools-base:1-abc") == [
        "podman", "build",
        "--file", str(tmp_path / "Dockerfile"),
        "--tag", "devops-tools-base:1-abc",
        str(tmp_path),
    ]  # fmt: skip


@pytest.mark.parametrize(
    ("dockerfile_text", "is_accepted"),
    [
        ("ARG BASE_IMAGE\nFROM ${BASE_IMAGE}\nRUN true\n", True),
        ("ARG BASE_IMAGE\nFROM ubuntu AS download\nFROM ${BASE_IMAGE}\n", True),
        ("FROM ubuntu:24.04\n", False),
        ("ARG BASE_IMAGE\nFROM ubuntu:24.04\n", False),
        ("FROM ${BASE_IMAGE}\n", False),
    ],
)
def test_check_dockerfile_builds_on_base_image(tmp_path, dockerfile_text, is_accepted):
    """
    What: check_dockerfile_builds_on_base_image.
    When: the project Dockerfile does or does not declare BASE_IMAGE and build a stage on it.
    Then: it is accepted, or refused with a message that shows the two lines to add.
    """
    write_versioned_checkout(tmp_path)
    (tmp_path / "container" / "Dockerfile").write_text(dockerfile_text)
    if is_accepted:
        check_dockerfile_builds_on_base_image(tmp_path, VERSIONED_SETTINGS)
        return
    with pytest.raises(ContainerSetupError, match=r"ARG BASE_IMAGE.*FROM \$\{BASE_IMAGE\}"):
        check_dockerfile_builds_on_base_image(tmp_path, VERSIONED_SETTINGS)


@pytest.mark.parametrize(
    ("extra_arguments", "expected"),
    [
        (["--rebuild-image", "--keep-cache", "claude"], (True, True, ["claude"])),
        (["claude", "--rebuild-image"], (False, False, ["claude", "--rebuild-image"])),
        ([], (False, False, [])),
    ],
)
def test_split_agent_leading_flags(extra_arguments, expected):
    """
    What: split_agent_leading_flags.
    When: the agent flags come first in any order, after the command, or not at all.
    Then: only leading flags count; the rest is the command.
    """
    assert split_agent_leading_flags(extra_arguments) == expected


def test_build_agent_image_tag_follows_the_project_image(monkeypatch):
    """
    What: build_agent_image_tag.
    When: the project image is `example:zig-1.2.3`, and when AGENT_IMAGE is set.
    Then: the tag is `example-agent:zig-1.2.3-<agent hash>`, or AGENT_IMAGE itself.
    """
    monkeypatch.delenv("AGENT_IMAGE", raising=False)
    agent_tag = build_agent_image_tag("example:zig-1.2.3")
    assert agent_tag.startswith("example-agent:zig-1.2.3-")
    assert len(agent_tag.rsplit("-", 1)[-1]) == 12
    monkeypatch.setenv("AGENT_IMAGE", "mine:agent")
    assert build_agent_image_tag("example:zig-1.2.3") == "mine:agent"
