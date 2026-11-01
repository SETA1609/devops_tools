import pytest

from devops_tools.exceptions import RepositorySettingsError
from devops_tools.models import RepositorySettings
from devops_tools.settings import read_repository_settings


def write_pyproject(directory, table_text):
    settings_file = directory / "pyproject.toml"
    settings_file.write_text(f'[project]\nname = "example"\n\n{table_text}')
    return settings_file


def test_read_repository_settings_without_a_pyproject_uses_the_defaults(tmp_path):
    assert read_repository_settings(tmp_path) == RepositorySettings()


def test_read_repository_settings_without_the_table_uses_the_defaults(tmp_path):
    write_pyproject(tmp_path, "")
    assert read_repository_settings(tmp_path) == RepositorySettings()


def test_read_repository_settings_reads_every_key(tmp_path):
    write_pyproject(
        tmp_path,
        "[tool.devops-tools]\n"
        'main-branch = "trunk"\n'
        "issue-id-pattern = 'AB-[0-9]{2}'\n"
        'changes-directory = "docs/changes"\n'
        'changelog-file = "docs/CHANGELOG.md"\n',
    )
    assert read_repository_settings(tmp_path) == RepositorySettings(
        main_branch="trunk",
        issue_id_pattern="AB-[0-9]{2}",
        changes_directory="docs/changes",
        changelog_file="docs/CHANGELOG.md",
    )


def test_read_repository_settings_reads_a_named_file_elsewhere(tmp_path):
    (tmp_path / "tools").mkdir()
    settings_file = write_pyproject(
        tmp_path / "tools", '[tool.devops-tools]\nmain-branch = "dev"\n'
    )
    settings = read_repository_settings(tmp_path, settings_file)
    assert settings.main_branch == "dev"


def test_read_repository_settings_requires_a_named_file_to_exist(tmp_path):
    with pytest.raises(RepositorySettingsError, match="cannot read"):
        read_repository_settings(tmp_path, tmp_path / "missing.toml")


@pytest.mark.parametrize(
    ("table_text", "expected_message"),
    [
        ('main-brnach = "main"\n', "unknown key"),
        ("main-branch = 3\n", "non-empty string"),
        ('main-branch = ""\n', "non-empty string"),
        ("issue-id-pattern = '[A-Z'\n", "not a regular expression"),
        ("issue-id-pattern = '(?P<issue_id>A-1)'\n", "named groups"),
        ("issue-id-pattern = 'A*'\n", "matches empty text"),
    ],
)
def test_read_repository_settings_rejects_bad_tables(tmp_path, table_text, expected_message):
    write_pyproject(tmp_path, f"[tool.devops-tools]\n{table_text}")
    with pytest.raises(RepositorySettingsError, match=expected_message):
        read_repository_settings(tmp_path)


def test_read_repository_settings_reads_a_list_of_patterns(tmp_path):
    write_pyproject(tmp_path, '[tool.devops-tools]\nkeep-both-added-lines = ["docs/*.md"]\n')
    assert read_repository_settings(tmp_path).keep_both_added_lines == ("docs/*.md",)


@pytest.mark.parametrize("value_text", ['"docs/*.md"', '["docs/*.md", 3]', '[""]', '["a b.md"]'])
def test_read_repository_settings_rejects_bad_pattern_lists(tmp_path, value_text):
    write_pyproject(tmp_path, f"[tool.devops-tools]\nkeep-both-added-lines = {value_text}\n")
    with pytest.raises(RepositorySettingsError, match="keep-both-added-lines"):
        read_repository_settings(tmp_path)
