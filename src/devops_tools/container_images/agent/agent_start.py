"""
Agent container start script: install what the project declares and is missing, then run the
command (default bash). It runs on every start, so a fresh home volume or a newly declared
plugin needs no manual step, and it is quick when nothing is missing.
1. Every marketplace in `.claude/settings.json` `extraKnownMarketplaces` that Claude Code does
   not know yet: `claude plugin marketplace add <source>`.
2. Every plugin set to true in `enabledPlugins` that is not installed:
   `claude plugin install <plugin>@<marketplace>` (user scope, kept in the home volume).
3. Every setup command the runner passes in DEVOPS_TOOLS_AGENT_SETUP_COMMANDS (a JSON list of
   argument lists), run in the checkout, such as `uv sync`.
A failed step is reported and the command still starts. Standard library only; this file is
copied into the agent image and runs on the image's system python3.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

PROJECT_SETTINGS_PATH = Path(".claude") / "settings.json"
SETUP_COMMANDS_ENVIRONMENT_VARIABLE = "DEVOPS_TOOLS_AGENT_SETUP_COMMANDS"
MESSAGE_PREFIX = "agent-start:"
DEFAULT_COMMAND = ("bash",)

CommandRunner = Callable[[Sequence[str]], subprocess.CompletedProcess]


def run_command_capturing_output(command: Sequence[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        list(command), stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False
    )


def write_message(text: str) -> None:
    print(f"{MESSAGE_PREFIX} {text}", file=sys.stderr, flush=True)


def read_project_settings(checkout_path: Path) -> dict:
    """
    The parsed `.claude/settings.json`, or an empty dict when it is missing or unreadable.
    """
    settings_path = checkout_path / PROJECT_SETTINGS_PATH
    try:
        parsed_settings = json.loads(settings_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as read_error:
        write_message(f"cannot read {settings_path}: {read_error}")
        return {}
    return parsed_settings if isinstance(parsed_settings, dict) else {}


def build_marketplace_source_argument(source: object) -> str | None:
    """
    The `claude plugin marketplace add` argument for an extraKnownMarketplaces source:
    `owner/repo#ref` for github, `<url>#ref` for git and url, the path for directory and file.
    None for a source it cannot express.
    """
    if not isinstance(source, dict):
        return None
    source_kind = source.get("source")
    reference = source.get("ref")
    reference_suffix = f"#{reference}" if isinstance(reference, str) and reference else ""
    if source_kind == "github" and isinstance(source.get("repo"), str):
        return f"{source['repo']}{reference_suffix}"
    if source_kind in ("git", "url") and isinstance(source.get("url"), str):
        return f"{source['url']}{reference_suffix}"
    if source_kind in ("directory", "file") and isinstance(source.get("path"), str):
        path_text = source["path"]
        is_explicit_path = path_text.startswith(("/", "./", "../"))
        return path_text if is_explicit_path else f"./{path_text}"
    return None


def list_declared_marketplaces(project_settings: dict) -> list[tuple[str, str | None]]:
    """
    (marketplace name, source argument or None) for each extraKnownMarketplaces entry.
    """
    marketplaces = project_settings.get("extraKnownMarketplaces")
    if not isinstance(marketplaces, dict):
        return []
    return [
        (marketplace_name, build_marketplace_source_argument(entry.get("source")))
        for marketplace_name, entry in sorted(marketplaces.items())
        if isinstance(entry, dict)
    ]


def list_enabled_plugin_ids(project_settings: dict) -> list[str]:
    """
    The `plugin@marketplace` keys of enabledPlugins whose value is true.
    """
    enabled_plugins = project_settings.get("enabledPlugins")
    if not isinstance(enabled_plugins, dict):
        return []
    return sorted(
        plugin_id
        for plugin_id, is_enabled in enabled_plugins.items()
        if is_enabled is True and "@" in plugin_id
    )


def read_json_listing(run_command: CommandRunner, command: Sequence[str]) -> list:
    completed = run_command(command)
    if completed.returncode != 0:
        return []
    try:
        listing = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return []
    return listing if isinstance(listing, list) else []


def install_declared_plugins(project_settings: dict, run_command: CommandRunner) -> int:
    """
    Add missing marketplaces and install missing enabled plugins. Returns the failure count.
    """
    known_marketplace_names = {
        entry.get("name")
        for entry in read_json_listing(
            run_command, ["claude", "plugin", "marketplace", "list", "--json"]
        )
        if isinstance(entry, dict)
    }
    failure_count = 0
    for marketplace_name, source_argument in list_declared_marketplaces(project_settings):
        if marketplace_name in known_marketplace_names:
            continue
        if source_argument is None:
            write_message(f"marketplace {marketplace_name}: source not supported, skipped")
            failure_count += 1
            continue
        write_message(f"adding marketplace {marketplace_name} from {source_argument}")
        completed = run_command(["claude", "plugin", "marketplace", "add", source_argument])
        if completed.returncode != 0:
            write_message(f"marketplace {marketplace_name} failed: {completed.stderr.strip()}")
            failure_count += 1
    installed_plugin_ids = {
        entry.get("id")
        for entry in read_json_listing(run_command, ["claude", "plugin", "list", "--json"])
        if isinstance(entry, dict)
    }
    for plugin_id in list_enabled_plugin_ids(project_settings):
        if plugin_id in installed_plugin_ids:
            continue
        write_message(f"installing plugin {plugin_id}")
        completed = run_command(["claude", "plugin", "install", plugin_id, "--scope", "user"])
        if completed.returncode != 0:
            write_message(f"plugin {plugin_id} failed: {completed.stderr.strip()}")
            failure_count += 1
    return failure_count


def read_setup_commands(environment: dict[str, str]) -> list[list[str]]:
    """
    The setup commands the runner passed, or an empty list when none or malformed.
    """
    raw_commands = environment.get(SETUP_COMMANDS_ENVIRONMENT_VARIABLE, "")
    if not raw_commands:
        return []
    try:
        parsed_commands = json.loads(raw_commands)
    except json.JSONDecodeError:
        write_message(f"{SETUP_COMMANDS_ENVIRONMENT_VARIABLE} is not JSON, setup skipped")
        return []
    is_valid = isinstance(parsed_commands, list) and all(
        isinstance(command, list) and command and all(isinstance(part, str) for part in command)
        for command in parsed_commands
    )
    if not is_valid:
        write_message(f"{SETUP_COMMANDS_ENVIRONMENT_VARIABLE} is not a list of commands")
        return []
    return parsed_commands


def run_setup_commands(setup_commands: list[list[str]], run_command: CommandRunner) -> int:
    """
    Run each setup command in order. Returns the failure count; a failure does not stop the rest.
    """
    failure_count = 0
    for setup_command in setup_commands:
        write_message(f"setup: {' '.join(setup_command)}")
        try:
            completed = run_command(setup_command)
        except FileNotFoundError:
            write_message(f"setup command not found: {setup_command[0]}")
            failure_count += 1
            continue
        if completed.returncode != 0:
            write_message(f"setup failed ({completed.returncode}): {completed.stderr.strip()}")
            failure_count += 1
    return failure_count


def prepare_agent_container(
    checkout_path: Path,
    environment: dict[str, str],
    run_command: CommandRunner,
    is_claude_installed: bool,
) -> int:
    """
    Plugins first, then setup commands. Returns the total failure count.
    """
    failure_count = 0
    if is_claude_installed:
        failure_count += install_declared_plugins(read_project_settings(checkout_path), run_command)
    else:
        write_message("claude is not installed; plugins skipped")
    failure_count += run_setup_commands(read_setup_commands(environment), run_command)
    if failure_count:
        write_message(f"{failure_count} step(s) failed; starting anyway, they retry next start")
    return failure_count


def main(argv: Sequence[str] | None = None) -> int:
    command = list(sys.argv[1:] if argv is None else argv) or list(DEFAULT_COMMAND)
    home_directory = Path(os.environ.get("HOME", "/tmp/container-home"))
    home_directory.mkdir(parents=True, exist_ok=True)
    prepare_agent_container(
        Path.cwd(),
        dict(os.environ),
        run_command_capturing_output,
        shutil.which("claude") is not None,
    )
    os.execvp(command[0], command)
    return 0


if __name__ == "__main__":
    sys.exit(main())
