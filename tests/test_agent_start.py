"""
The agent container start script, shipped in the agent image and run there on every start.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import subprocess
import sys

import pytest

from devops_tools.container import get_shipped_images_directory

START_SCRIPT_PATH = get_shipped_images_directory("agent") / "agent_start.py"


def load_start_script():
    spec = importlib.util.spec_from_file_location("agent_start", START_SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["agent_start"] = module
    spec.loader.exec_module(module)
    return module


START = load_start_script()

PROJECT_SETTINGS = {
    "extraKnownMarketplaces": {
        "devops-tools": {"source": {"source": "github", "repo": "owner/tools", "ref": "v0.2.0"}},
        "already-known": {"source": {"source": "github", "repo": "owner/known"}},
    },
    "enabledPlugins": {
        "devops-tools@devops-tools": True,
        "installed@already-known": True,
        "switched-off@already-known": False,
    },
}


class FakeClaude:
    """
    Records commands and answers the two JSON listings like `claude` 2.1 does.
    """

    def __init__(self, failing_prefixes=()):
        self.commands = []
        self.failing_prefixes = failing_prefixes

    def __call__(self, command):
        self.commands.append(list(command))
        text = " ".join(command)
        if any(text.startswith(prefix) for prefix in self.failing_prefixes):
            return subprocess.CompletedProcess(command, 1, "", "network down")
        if text == "claude plugin marketplace list --json":
            return subprocess.CompletedProcess(
                command, 0, json.dumps([{"name": "already-known"}]), ""
            )
        if text == "claude plugin list --json":
            return subprocess.CompletedProcess(
                command, 0, json.dumps([{"id": "installed@already-known"}]), ""
            )
        return subprocess.CompletedProcess(command, 0, "", "")


@pytest.mark.parametrize(
    ("source", "expected_argument"),
    [
        ({"source": "github", "repo": "owner/tools", "ref": "v1.2.0"}, "owner/tools#v1.2.0"),
        ({"source": "github", "repo": "owner/tools"}, "owner/tools"),
        (
            {"source": "git", "url": "https://host/tools.git", "ref": "main"},
            "https://host/tools.git#main",
        ),
        ({"source": "directory", "path": "tools/marketplace"}, "./tools/marketplace"),
        ({"source": "file", "path": "/abs/marketplace.json"}, "/abs/marketplace.json"),
        ({"source": "npm", "package": "x"}, None),
        ("owner/tools", None),
    ],
)
def test_build_marketplace_source_argument(source, expected_argument):
    """
    What: build_marketplace_source_argument.
    When: an extraKnownMarketplaces source is github, git, a path, or something unsupported.
    Then: it becomes the `claude plugin marketplace add` argument with `#ref` for a pinned
    ref, a `./` prefix for a relative path, or None.
    """
    assert START.build_marketplace_source_argument(source) == expected_argument


def test_install_declared_plugins_adds_and_installs_only_what_is_missing():
    """
    What: install_declared_plugins.
    When: one marketplace and one enabled plugin are missing, the others are present or off.
    Then: only the missing marketplace is added (with its ref) and only the missing enabled
    plugin is installed, at user scope, with no failures.
    """
    fake_claude = FakeClaude()
    assert START.install_declared_plugins(PROJECT_SETTINGS, fake_claude) == 0
    changing_commands = [command for command in fake_claude.commands if "--json" not in command]
    assert changing_commands == [
        ["claude", "plugin", "marketplace", "add", "owner/tools#v0.2.0"],
        ["claude", "plugin", "install", "devops-tools@devops-tools", "--scope", "user"],
    ]


def test_install_declared_plugins_counts_failures_and_keeps_going():
    """
    What: install_declared_plugins.
    When: adding the marketplace fails.
    Then: the failure is counted and the plugin install is still tried.
    """
    fake_claude = FakeClaude(failing_prefixes=("claude plugin marketplace add",))
    assert START.install_declared_plugins(PROJECT_SETTINGS, fake_claude) == 1
    assert ["claude", "plugin", "install", "devops-tools@devops-tools", "--scope", "user"] in (
        fake_claude.commands
    )


@pytest.mark.parametrize(
    ("environment_value", "expected_commands"),
    [
        ('[["uv", "sync"], ["git", "status"]]', [["uv", "sync"], ["git", "status"]]),
        ("", []),
        ("not json", []),
        ('[["uv", 3]]', []),
        ("[[]]", []),
    ],
)
def test_read_setup_commands(environment_value, expected_commands):
    """
    What: read_setup_commands.
    When: the environment holds a JSON list of commands, nothing, or something malformed.
    Then: valid commands come back in order; anything else gives no commands.
    """
    environment = {"DEVOPS_TOOLS_AGENT_SETUP_COMMANDS": environment_value}
    assert START.read_setup_commands(environment) == expected_commands


def test_prepare_agent_container_runs_plugins_then_setup_and_survives_failures(tmp_path):
    """
    What: prepare_agent_container.
    When: the checkout declares plugins and one setup command fails.
    Then: plugins are handled first, every setup command runs, and the failure is counted
    without raising, so the agent still starts.
    """
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text(json.dumps(PROJECT_SETTINGS))
    fake_claude = FakeClaude(failing_prefixes=("uv sync",))
    environment = {"DEVOPS_TOOLS_AGENT_SETUP_COMMANDS": '[["uv", "sync"], ["git", "status"]]'}
    assert START.prepare_agent_container(tmp_path, environment, fake_claude, True) == 1
    command_texts = [" ".join(command) for command in fake_claude.commands]
    assert command_texts.index("claude plugin install devops-tools@devops-tools --scope user") < (
        command_texts.index("uv sync")
    )
    assert command_texts[-1] == "git status"


def test_prepare_agent_container_without_claude_or_settings_only_runs_setup(tmp_path):
    """
    What: prepare_agent_container.
    When: claude is not installed and the checkout has no .claude/settings.json.
    Then: no claude command runs and the setup commands still do.
    """
    fake_claude = FakeClaude()
    environment = {"DEVOPS_TOOLS_AGENT_SETUP_COMMANDS": '[["uv", "sync"]]'}
    assert START.prepare_agent_container(tmp_path, environment, fake_claude, False) == 0
    assert fake_claude.commands == [["uv", "sync"]]


def test_the_start_script_runs_on_python_3_12():
    """
    What: the start script file.
    When: it is compiled with the oldest Python the agent image may run it on.
    Then: it uses no syntax newer than the image's system python3 (3.12 on Ubuntu 24.04).
    """
    source_text = START_SCRIPT_PATH.read_text()
    ast.parse(source_text, filename=str(START_SCRIPT_PATH), feature_version=(3, 12))
