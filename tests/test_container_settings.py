import pytest

from devops_tools.exceptions import RepositorySettingsError
from devops_tools.models import ContainerSettings, VersionPin
from devops_tools.settings import read_repository_settings

FULL_CONTAINER_TABLE = """
[tool.devops-tools.container]
image = "example"
dockerfile = "docker/Dockerfile"
toolchain = "zig"
version-file = ".tool-version"
version-argument = "TOOL_VERSION"
version-pins = [{ file = "devcontainer.json", pattern = 'example:zig-([0-9.]+)' }]
home-directory = "/tmp/example-home"
cache-environment-variable = "TOOL_CACHE_DIR"
cache-volume = "example-cache"
read-only-symlink-mounts = ["references/data"]
clean-directories = ["build-output"]
protected-directories = ["references", "cache/logs"]

[tool.devops-tools.container.commands]
test = ["tool", "build", "test"]
build = ["tool", "build"]
"""


def read_container_table(tmp_path, table_text):
    (tmp_path / "pyproject.toml").write_text(table_text)
    return read_repository_settings(tmp_path).container


def test_settings_without_a_container_table_have_no_container(tmp_path):
    """
    What: reading repository settings.
    When: pyproject.toml has no [tool.devops-tools.container] table.
    Then: the container settings are None.
    """
    assert read_container_table(tmp_path, "[tool.devops-tools]\n") is None


def test_container_table_reads_every_key(tmp_path):
    """
    What: the [tool.devops-tools.container] table.
    When: every key is set.
    Then: each lands in ContainerSettings, with commands sorted by name.
    """
    assert read_container_table(tmp_path, FULL_CONTAINER_TABLE) == ContainerSettings(
        image="example",
        dockerfile="docker/Dockerfile",
        toolchain="zig",
        version_file=".tool-version",
        version_argument="TOOL_VERSION",
        version_pins=(VersionPin(file="devcontainer.json", pattern="example:zig-([0-9.]+)"),),
        home_directory="/tmp/example-home",
        cache_environment_variable="TOOL_CACHE_DIR",
        cache_volume="example-cache",
        read_only_symlink_mounts=("references/data",),
        clean_directories=("build-output",),
        protected_directories=("references", "cache/logs"),
        commands=(("build", ("tool", "build")), ("test", ("tool", "build", "test"))),
    )


def test_container_table_with_only_an_image_uses_the_defaults(tmp_path):
    """
    What: the [tool.devops-tools.container] table.
    When: it sets only `image`.
    Then: every other field has its default.
    """
    container_settings = read_container_table(
        tmp_path, '[tool.devops-tools.container]\nimage = "example"\n'
    )
    assert container_settings == ContainerSettings(image="example")


@pytest.mark.parametrize(
    ("table_text", "expected_message"),
    [
        ("dockerfile = 'x'\n", "image must be a non-empty string"),
        ("image = 'Example:1'\n", "lowercase image name without a tag"),
        ("image = 'e'\nversion-file = '.v'\n", "go together"),
        ("image = 'e'\ncache-volume = 'c'\n", "needs cache-environment-variable"),
        ("image = 'e'\nhome-directory = 'home'\n", "absolute path"),
        ("image = 'e'\nmounts = []\n", "unknown key"),
        ("image = 'e'\nversion-pins = [{ file = 'f', pattern = 'x' }]\n", "one group"),
        ("image = 'e'\nversion-pins = [{ file = 'f' }]\n", "one group"),
        ("image = 'e'\nclean-directories = 'zig-out'\n", "list of path patterns"),
        ("image = 'e'\ncommands = { image = ['x'] }\n", "shadows a built-in action"),
        ("image = 'e'\ncommands = { Build = ['x'] }\n", "lowercase"),
        ("image = 'e'\ncommands = { build = [] }\n", "non-empty list of strings"),
        ("image = 'e'\ncommands = ['x']\n", "must be a table"),
    ],
)
def test_container_table_rejects_bad_settings(tmp_path, table_text, expected_message):
    """
    What: the [tool.devops-tools.container] table.
    When: a key is missing, mistyped, unknown, or contradicts another key.
    Then: reading fails with a message that names the problem.
    """
    with pytest.raises(RepositorySettingsError, match=expected_message):
        read_container_table(tmp_path, f"[tool.devops-tools.container]\n{table_text}")
