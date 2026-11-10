"""
Safety rules for the GitHub workflows in .github/workflows, checked on the text.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

WORKFLOW_DIRECTORY = Path(__file__).resolve().parents[1] / ".github" / "workflows"
WORKFLOW_PATHS = sorted(WORKFLOW_DIRECTORY.glob("*.yml"))
REUSABLE_WORKFLOW_PATHS = [
    path for path in WORKFLOW_PATHS if "workflow_call:" in path.read_text(encoding="utf-8")
]
SCRIPT_DIRECTORY = Path(__file__).resolve().parents[1] / "scripts" / "workflows"
SCRIPT_PATHS = sorted(SCRIPT_DIRECTORY.glob("*.sh"))
RUN_LINE = re.compile(r"^\s*(?:-\s+)?run:\s*(?P<command>.*)$", re.MULTILINE)
SCRIPT_CALL = re.compile(
    r'bash (?:"\$GITHUB_WORKSPACE/devops-tools-checkout/)?scripts/workflows/'
    r'(?P<script_name>[a-z_]+\.sh)"?(?: [a-z]+)?'
)
USES_LINE = re.compile(r"^\s*(?:-\s+)?uses:\s*(?P<reference>\S+)(?P<comment>.*)$", re.MULTILINE)
PINNED_ACTION = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")
VERSION_COMMENT = re.compile(r"^\s+#\s+v[0-9]")


def list_run_commands(workflow_text: str) -> list[str]:
    """
    The value of every `run:` key in a workflow; a block scalar comes back as its `|` marker.
    """
    return [match.group("command") for match in RUN_LINE.finditer(workflow_text)]


def test_the_repository_has_the_four_reusable_workflows():
    """
    What: the reusable workflows in .github/workflows.
    When: the test suite runs.
    Then: issue closing, rebase, changelog fragment, and submodule pin workflows exist.
    """
    assert [path.name for path in REUSABLE_WORKFLOW_PATHS] == [
        "changelog-fragments.yml",
        "close-merged-issue.yml",
        "rebase-open-branches.yml",
        "submodule-pins.yml",
    ]


@pytest.mark.parametrize("workflow_path", WORKFLOW_PATHS, ids=lambda path: path.name)
def test_every_action_is_pinned_to_a_commit_with_its_version_in_a_comment(workflow_path):
    """
    What: each `uses:` line of a workflow.
    When: it names a GitHub Action.
    Then: the reference is a full 40-character commit SHA followed by a `# vX` comment.
    """
    for uses_match in USES_LINE.finditer(workflow_path.read_text(encoding="utf-8")):
        assert PINNED_ACTION.match(uses_match.group("reference")), uses_match.group(0)
        assert VERSION_COMMENT.match(uses_match.group("comment")), uses_match.group(0)


@pytest.mark.parametrize("workflow_path", WORKFLOW_PATHS, ids=lambda path: path.name)
def test_every_workflow_declares_its_permissions(workflow_path):
    """
    What: the top level of a workflow.
    When: the workflow is read.
    Then: it has a `permissions:` key, so it never runs with the repository default.
    """
    assert re.search(r"^permissions:", workflow_path.read_text(encoding="utf-8"), re.MULTILINE)


@pytest.mark.parametrize("workflow_path", WORKFLOW_PATHS, ids=lambda path: path.name)
def test_every_run_step_only_calls_a_committed_script(workflow_path):
    """
    What: the `run:` steps of a workflow.
    When: the workflow is read.
    Then: each is one `bash` call of a script in scripts/workflows that exists, with no inline
    scripting and no `${{ }}` expansion; inputs and event values come in through `env:`.
    """
    run_commands = list_run_commands(workflow_path.read_text(encoding="utf-8"))
    assert run_commands
    for run_command in run_commands:
        command_match = SCRIPT_CALL.fullmatch(run_command)
        assert command_match, run_command
        assert (SCRIPT_DIRECTORY / command_match.group("script_name")).is_file(), run_command


@pytest.mark.parametrize("workflow_path", REUSABLE_WORKFLOW_PATHS, ids=lambda path: path.name)
def test_reusable_workflows_check_the_version_before_running_it(workflow_path):
    """
    What: a reusable workflow that runs devops-tools.
    When: the caller passes `devops-tools-version`.
    Then: the version check is its first `run:` step, so a bad version never reaches uvx.
    """
    workflow_text = workflow_path.read_text(encoding="utf-8")
    assert re.search(r"^      devops-tools-version:\n        description:", workflow_text, re.M)
    run_commands = list_run_commands(workflow_text)
    assert "check_devops_tools_version.sh" in run_commands[0]
    assert len(run_commands) == 2


@pytest.mark.parametrize("script_path", SCRIPT_PATHS, ids=lambda path: path.name)
def test_every_workflow_script_says_what_it_does(script_path):
    """
    What: a script in scripts/workflows.
    When: it is read.
    Then: it starts with a bash shebang, a comment header with a usage line, and strict mode.
    """
    script_text = script_path.read_text(encoding="utf-8")
    assert script_text.startswith("#!/usr/bin/env bash\n# ")
    assert "# Usage: " in script_text
    assert "set -euo pipefail\n" in script_text


@pytest.mark.parametrize(
    ("version", "expected_exit_code"), [("a" * 40, 0), ("main", 1), ("a" * 39, 1)]
)
def test_the_version_check_accepts_only_a_full_commit_sha(version, expected_exit_code):
    """
    What: check_devops_tools_version.sh.
    When: it gets a full commit SHA, a branch name, or a shortened SHA.
    Then: only the full commit SHA passes.
    """
    completed = subprocess.run(
        ["bash", str(SCRIPT_DIRECTORY / "check_devops_tools_version.sh")],
        env={**os.environ, "DEVOPS_TOOLS_VERSION": version},
        capture_output=True,
        check=False,
    )
    assert completed.returncode == expected_exit_code


def run_git(directory: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *arguments],
        cwd=directory,
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.strip()


FAKE_UVX_CHANGES_A_FILE = """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$FAKE_UVX_ARGUMENT_LOG"
echo closed > closed-issue.md
"""
FAKE_UVX_CHANGES_NOTHING = """#!/usr/bin/env bash
exit 0
"""
FAKE_UVX_LOSES_THE_FIRST_RACE = """#!/usr/bin/env bash
if [ ! -e "$FAKE_RACE_MARKER" ]; then
    touch "$FAKE_RACE_MARKER"
    git -C "$FAKE_RIVAL_CLONE" -c user.name=t -c user.email=t@example.com \\
        commit --allow-empty -q -m "rival merge"
    git -C "$FAKE_RIVAL_CLONE" push -q origin HEAD:main
fi
echo closed > closed-issue.md
"""


@pytest.fixture
def close_script_workspace(tmp_path: Path) -> dict[str, Path]:
    """
    A bare origin with one commit on main, a clone for the script, and a rival clone.
    """
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    seed = tmp_path / "seed"
    subprocess.run(["git", "clone", "-q", str(origin), str(seed)], capture_output=True, check=True)
    run_git(seed, "commit", "--allow-empty", "-q", "-m", "first")
    run_git(seed, "push", "-q", "origin", "HEAD:main")
    clone = tmp_path / "clone"
    rival = tmp_path / "rival"
    for destination in (clone, rival):
        subprocess.run(["git", "clone", "-q", str(origin), str(destination)], check=True)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    return {"origin": origin, "clone": clone, "rival": rival, "bin": fake_bin, "root": tmp_path}


def run_close_script(workspace: dict[str, Path], fake_uvx_text: str) -> subprocess.CompletedProcess:
    fake_uvx = workspace["bin"] / "uvx"
    fake_uvx.write_text(fake_uvx_text, encoding="utf-8")
    fake_uvx.chmod(0o755)
    return subprocess.run(
        ["bash", str(SCRIPT_DIRECTORY / "close_merged_issue.sh")],
        cwd=workspace["clone"],
        env={
            **os.environ,
            "PATH": f"{workspace['bin']}{os.pathsep}{os.environ['PATH']}",
            "DEVOPS_TOOLS_VERSION": "a" * 40,
            "BASE_BRANCH": "main",
            "HEAD_BRANCH": "ab-01-slug",
            "PULL_REQUEST_NUMBER": "7",
            "MERGED_AT": "2026-01-02T03:04:05Z",
            "RETRY_DELAY_SECONDS": "0",
            "FAKE_UVX_ARGUMENT_LOG": str(workspace["root"] / "uvx-arguments.log"),
            "FAKE_RACE_MARKER": str(workspace["root"] / "race-marker"),
            "FAKE_RIVAL_CLONE": str(workspace["rival"]),
        },
        capture_output=True,
        text=True,
        check=False,
    )


def test_the_close_script_commits_and_pushes_the_closed_issue(close_script_workspace):
    """
    What: close_merged_issue.sh.
    When: the tool changes a file.
    Then: main on origin gets one commit naming the pull request, and the tool got the branch,
    the number, and the date part of the merge time.
    """
    completed = run_close_script(close_script_workspace, FAKE_UVX_CHANGES_A_FILE)
    assert completed.returncode == 0, completed.stderr
    origin = close_script_workspace["origin"]
    assert run_git(origin, "log", "-1", "--format=%s", "main") == (
        "Close the issue of pull request #7"
    )
    assert "closed-issue.md" in run_git(origin, "ls-tree", "--name-only", "main")
    logged_arguments = (close_script_workspace["root"] / "uvx-arguments.log").read_text("utf-8")
    assert "--branch ab-01-slug --pull-request-number 7 --merge-date 2026-01-02" in logged_arguments


def test_the_close_script_pushes_nothing_when_nothing_changed(close_script_workspace):
    """
    What: close_merged_issue.sh.
    When: the tool changes no file.
    Then: the script succeeds and main on origin has no new commit.
    """
    origin = close_script_workspace["origin"]
    head_before = run_git(origin, "rev-parse", "main")
    completed = run_close_script(close_script_workspace, FAKE_UVX_CHANGES_NOTHING)
    assert completed.returncode == 0, completed.stderr
    assert run_git(origin, "rev-parse", "main") == head_before


def test_the_close_script_starts_again_when_its_push_loses_a_race(close_script_workspace):
    """
    What: close_merged_issue.sh.
    When: another merge lands on main between the script's fetch and its push.
    Then: the script retries from the new main, so both the rival commit and its own are on main.
    """
    completed = run_close_script(close_script_workspace, FAKE_UVX_LOSES_THE_FIRST_RACE)
    assert completed.returncode == 0, completed.stderr
    subjects = run_git(close_script_workspace["origin"], "log", "--format=%s", "main").splitlines()
    assert subjects[:2] == ["Close the issue of pull request #7", "rival merge"]
