"""
The Claude Code plugin and marketplace manifests agree with the package they ship.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

import pytest

from devops_tools.cli import REPOSITORY_WORKFLOW_SUBCOMMANDS

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
MARKETPLACE_PATH = REPOSITORY_ROOT / ".claude-plugin" / "marketplace.json"
PLUGIN_MANIFEST_PATH = REPOSITORY_ROOT / ".claude-plugin" / "plugin.json"
SKILL_PATHS = sorted((REPOSITORY_ROOT / "skills").glob("*/SKILL.md"))
SKILL_COMMAND = re.compile(
    r'uvx --from "\$\{CLAUDE_PLUGIN_ROOT\}" devops-tools (?P<subcommand>[a-z-]+)'
)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_the_plugin_version_is_the_package_version():
    """
    What: .claude-plugin/plugin.json.
    When: it is compared with pyproject.toml.
    Then: both carry the same version, so a plugin update and a package release move together.
    """
    package_version = tomllib.loads((REPOSITORY_ROOT / "pyproject.toml").read_text())["project"][
        "version"
    ]
    assert read_json(PLUGIN_MANIFEST_PATH)["version"] == package_version


def test_the_marketplace_lists_this_repository_as_the_plugin():
    """
    What: .claude-plugin/marketplace.json.
    When: its one plugin entry is read.
    Then: the entry names the plugin as plugin.json does and its source is the repository
    root, so ${CLAUDE_PLUGIN_ROOT} holds pyproject.toml and the package.
    """
    marketplace = read_json(MARKETPLACE_PATH)
    (plugin_entry,) = marketplace["plugins"]
    assert plugin_entry["name"] == read_json(PLUGIN_MANIFEST_PATH)["name"]
    assert plugin_entry["source"] == "./"
    assert marketplace["owner"]["name"]


def test_the_plugin_ships_the_three_skills():
    """
    What: the skills directory.
    When: the plugin is packaged.
    Then: it holds fetch-docs, roadmap-order, and status-report.
    """
    assert [path.parent.name for path in SKILL_PATHS] == [
        "fetch-docs",
        "roadmap-order",
        "status-report",
    ]


@pytest.mark.parametrize("skill_path", SKILL_PATHS, ids=lambda path: path.parent.name)
def test_each_skill_runs_a_real_subcommand_from_the_plugin_root(skill_path):
    """
    What: a skill's SKILL.md.
    When: it tells Claude how to run the tool.
    Then: its front matter names the skill after its directory, and every command runs
    `uvx --from "${CLAUDE_PLUGIN_ROOT}" devops-tools <subcommand>` with a subcommand that exists.
    """
    skill_text = skill_path.read_text(encoding="utf-8")
    assert re.search(rf"^name: {re.escape(skill_path.parent.name)}$", skill_text, re.MULTILINE)
    subcommands = {match.group("subcommand") for match in SKILL_COMMAND.finditer(skill_text)}
    assert subcommands
    assert subcommands <= set(REPOSITORY_WORKFLOW_SUBCOMMANDS)
