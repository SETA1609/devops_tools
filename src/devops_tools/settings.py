"""
Reading a project's `[tool.devops-tools]` table from a pyproject.toml.
Keys are kebab-case versions of the RepositorySettings fields; a missing file or table means
the defaults. Unknown keys and values of the wrong type are errors, so a typo is not ignored.
"""

from __future__ import annotations

import dataclasses
import re
import tomllib
from pathlib import Path

from devops_tools.constants import (
    BUILT_IN_CONTAINER_ACTIONS,
    CONTAINER_COMMAND_NAME_PATTERN,
    CONTAINER_IMAGE_NAME_PATTERN,
    CONTAINER_SETTINGS_TABLE_NAME,
    SETTINGS_FILE_NAME,
    SETTINGS_TABLE_PATH,
)
from devops_tools.exceptions import RepositorySettingsError
from devops_tools.models import ContainerSettings, RepositorySettings, VersionPin


def convert_field_name_to_settings_key(field_name: str) -> str:
    return field_name.replace("_", "-")


def build_repository_settings(table: dict[str, object], source_name: str) -> RepositorySettings:
    """
    RepositorySettings from a parsed table; `source_name` names the file in error messages.
    """
    field_names_by_key = {
        convert_field_name_to_settings_key(field.name): field.name
        for field in dataclasses.fields(RepositorySettings)
        if field.name != CONTAINER_SETTINGS_TABLE_NAME
    }
    table = dict(table)
    container_table = table.pop(CONTAINER_SETTINGS_TABLE_NAME, None)
    unknown_keys = sorted(set(table) - set(field_names_by_key))
    if unknown_keys:
        raise RepositorySettingsError(
            f"{source_name}: unknown key(s) in [tool.devops-tools]: {', '.join(unknown_keys)}; "
            f"known: {', '.join(sorted(field_names_by_key))}"
        )
    default_settings = RepositorySettings()
    values: dict[str, str | bool | tuple[str, ...]] = {}
    for key, value in table.items():
        field_name = field_names_by_key[key]
        if isinstance(getattr(default_settings, field_name), bool):
            if not isinstance(value, bool):
                raise RepositorySettingsError(
                    f"{source_name}: [tool.devops-tools] {key} must be true or false"
                )
            values[field_name] = value
            continue
        if isinstance(getattr(default_settings, field_name), tuple):
            values[field_name] = convert_pattern_list(key, value, source_name)
            continue
        if not isinstance(value, str) or not value:
            raise RepositorySettingsError(
                f"{source_name}: [tool.devops-tools] {key} must be a non-empty string"
            )
        values[field_name] = value
    settings = RepositorySettings(**values)
    validate_issue_id_pattern(settings.issue_id_pattern, source_name)
    if container_table is None:
        return settings
    if not isinstance(container_table, dict):
        raise RepositorySettingsError(
            f"{source_name}: [tool.devops-tools.container] must be a table"
        )
    return dataclasses.replace(
        settings, container=build_container_settings(container_table, source_name)
    )


def read_required_string(table: dict[str, object], key: str, source_name: str) -> str:
    value = table.get(key)
    if not isinstance(value, str) or not value:
        raise RepositorySettingsError(
            f"{source_name}: [tool.devops-tools.container] {key} must be a non-empty string"
        )
    return value


def read_optional_string(table: dict[str, object], key: str, source_name: str) -> str | None:
    return read_required_string(table, key, source_name) if key in table else None


def read_version_pins(value: object, source_name: str) -> tuple[VersionPin, ...]:
    """
    A list of `{ file = "...", pattern = "..." }`; each pattern has exactly one group.
    """
    message = (
        f"{source_name}: [tool.devops-tools.container] version-pins must be a list of "
        "{ file = ..., pattern = ... } tables whose pattern has one group"
    )
    if not isinstance(value, list):
        raise RepositorySettingsError(message)
    version_pins: list[VersionPin] = []
    for pin_table in value:
        if not isinstance(pin_table, dict) or set(pin_table) != {"file", "pattern"}:
            raise RepositorySettingsError(message)
        file_path, pattern = pin_table["file"], pin_table["pattern"]
        if not isinstance(file_path, str) or not isinstance(pattern, str) or not file_path:
            raise RepositorySettingsError(message)
        try:
            group_count = re.compile(pattern).groups
        except re.error as pattern_error:
            raise RepositorySettingsError(f"{message}: {pattern_error}") from pattern_error
        if group_count != 1:
            raise RepositorySettingsError(message)
        version_pins.append(VersionPin(file=file_path, pattern=pattern))
    return tuple(version_pins)


def read_container_commands(
    value: object, source_name: str
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """
    `{ build = ["zig", "build"] }` → (("build", ("zig", "build")),), sorted by name.
    Names are lowercase words joined by dashes and must not shadow a built-in action.
    """
    if not isinstance(value, dict):
        raise RepositorySettingsError(
            f"{source_name}: [tool.devops-tools.container.commands] must be a table"
        )
    commands: list[tuple[str, tuple[str, ...]]] = []
    for command_name, command in sorted(value.items()):
        if not CONTAINER_COMMAND_NAME_PATTERN.fullmatch(command_name):
            raise RepositorySettingsError(
                f"{source_name}: container command name {command_name!r} must be lowercase "
                "letters, digits, and dashes"
            )
        if command_name in BUILT_IN_CONTAINER_ACTIONS:
            raise RepositorySettingsError(
                f"{source_name}: container command {command_name!r} shadows a built-in action"
            )
        is_valid_command = (
            isinstance(command, list)
            and command
            and all(isinstance(part, str) and part for part in command)
        )
        if not is_valid_command:
            raise RepositorySettingsError(
                f"{source_name}: container command {command_name!r} must be a non-empty list "
                "of strings"
            )
        commands.append((command_name, tuple(command)))
    return tuple(commands)


def read_agent_setup_commands(value: object, source_name: str) -> tuple[tuple[str, ...], ...]:
    """
    `[["uv", "sync"]]` → (("uv", "sync"),): each command a non-empty list of strings.
    """
    is_valid = isinstance(value, list) and all(
        isinstance(command, list)
        and command
        and all(isinstance(part, str) and part for part in command)
        for command in value
    )
    if not is_valid:
        raise RepositorySettingsError(
            f"{source_name}: [tool.devops-tools.container] agent-setup-commands must be a list "
            "of non-empty lists of strings"
        )
    return tuple(tuple(command) for command in value)


def build_container_settings(table: dict[str, object], source_name: str) -> ContainerSettings:
    """
    ContainerSettings from the `[tool.devops-tools.container]` table, with cross-key checks.
    """
    string_keys = {
        "image", "dockerfile", "toolchain", "version-file", "version-argument",
        "home-directory", "cache-environment-variable", "cache-volume",
        "agent-home-volume", "agent-claude-code-version",
    }  # fmt: skip
    list_keys = {"read-only-symlink-mounts", "clean-directories", "protected-directories"}
    known_keys = string_keys | list_keys | {"version-pins", "commands", "agent-setup-commands"}
    unknown_keys = sorted(set(table) - known_keys)
    if unknown_keys:
        raise RepositorySettingsError(
            f"{source_name}: unknown key(s) in [tool.devops-tools.container]: "
            f"{', '.join(unknown_keys)}; known: {', '.join(sorted(known_keys))}"
        )
    values: dict[str, object] = {"image": read_required_string(table, "image", source_name)}
    for key in sorted(string_keys - {"image"}):
        if key in table:
            values[key.replace("-", "_")] = read_required_string(table, key, source_name)
    for key in sorted(list_keys):
        if key in table:
            values[key.replace("-", "_")] = convert_pattern_list(key, table[key], source_name)
    if "version-pins" in table:
        values["version_pins"] = read_version_pins(table["version-pins"], source_name)
    if "commands" in table:
        values["commands"] = read_container_commands(table["commands"], source_name)
    if "agent-setup-commands" in table:
        values["agent_setup_commands"] = read_agent_setup_commands(
            table["agent-setup-commands"], source_name
        )
    container_settings = ContainerSettings(**values)  # type: ignore[arg-type]
    if not CONTAINER_IMAGE_NAME_PATTERN.fullmatch(container_settings.image):
        raise RepositorySettingsError(
            f"{source_name}: container image {container_settings.image!r} must be a lowercase "
            "image name without a tag"
        )
    if (container_settings.version_file is None) != (container_settings.version_argument is None):
        raise RepositorySettingsError(
            f"{source_name}: container version-file and version-argument go together"
        )
    if container_settings.cache_volume and not container_settings.cache_environment_variable:
        raise RepositorySettingsError(
            f"{source_name}: container cache-volume needs cache-environment-variable"
        )
    if not container_settings.home_directory.startswith("/"):
        raise RepositorySettingsError(
            f"{source_name}: container home-directory must be an absolute path"
        )
    return container_settings


def convert_pattern_list(key: str, value: object, source_name: str) -> tuple[str, ...]:
    """
    A TOML list of gitattributes patterns → tuple. Patterns cannot hold whitespace, because
    gitattributes splits a line on it.
    """
    is_valid_list = isinstance(value, list) and all(
        isinstance(pattern, str) and pattern and not any(part.isspace() for part in pattern)
        for pattern in value
    )
    if not is_valid_list:
        raise RepositorySettingsError(
            f"{source_name}: [tool.devops-tools] {key} must be a list of path patterns "
            "without spaces"
        )
    return tuple(value)


def validate_issue_id_pattern(issue_id_pattern: str, source_name: str) -> None:
    try:
        compiled_pattern = re.compile(issue_id_pattern)
    except re.error as pattern_error:
        raise RepositorySettingsError(
            f"{source_name}: issue-id-pattern is not a regular expression: {pattern_error}"
        ) from pattern_error
    if compiled_pattern.groupindex:
        raise RepositorySettingsError(f"{source_name}: issue-id-pattern must not have named groups")
    if compiled_pattern.fullmatch(""):
        raise RepositorySettingsError(f"{source_name}: issue-id-pattern matches empty text")


def read_repository_settings(
    repository: Path, settings_file: Path | None = None
) -> RepositorySettings:
    """
    Settings from `settings_file`, or else from `<repository>/pyproject.toml` if it exists.
    A named settings file must exist; the default one may be missing.
    """
    if settings_file is None:
        settings_file = repository / SETTINGS_FILE_NAME
        if not settings_file.is_file():
            return RepositorySettings()
    try:
        parsed_document = tomllib.loads(settings_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as read_error:
        raise RepositorySettingsError(f"{settings_file}: cannot read: {read_error}") from read_error
    table: object = parsed_document
    for table_name in SETTINGS_TABLE_PATH:
        table = table.get(table_name, {}) if isinstance(table, dict) else {}
    if not isinstance(table, dict):
        raise RepositorySettingsError(f"{settings_file}: [tool.devops-tools] must be a table")
    return build_repository_settings(table, str(settings_file))
