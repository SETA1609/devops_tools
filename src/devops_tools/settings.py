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

from devops_tools.constants import SETTINGS_FILE_NAME, SETTINGS_TABLE_PATH
from devops_tools.exceptions import RepositorySettingsError
from devops_tools.models import RepositorySettings


def convert_field_name_to_settings_key(field_name: str) -> str:
    return field_name.replace("_", "-")


def build_repository_settings(table: dict[str, object], source_name: str) -> RepositorySettings:
    """
    RepositorySettings from a parsed table; `source_name` names the file in error messages.
    """
    field_names_by_key = {
        convert_field_name_to_settings_key(field.name): field.name
        for field in dataclasses.fields(RepositorySettings)
    }
    unknown_keys = sorted(set(table) - set(field_names_by_key))
    if unknown_keys:
        raise RepositorySettingsError(
            f"{source_name}: unknown key(s) in [tool.devops-tools]: {', '.join(unknown_keys)}; "
            f"known: {', '.join(sorted(field_names_by_key))}"
        )
    values: dict[str, str] = {}
    for key, value in table.items():
        if not isinstance(value, str) or not value:
            raise RepositorySettingsError(
                f"{source_name}: [tool.devops-tools] {key} must be a non-empty string"
            )
        values[field_names_by_key[key]] = value
    settings = RepositorySettings(**values)
    validate_issue_id_pattern(settings.issue_id_pattern, source_name)
    return settings


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
