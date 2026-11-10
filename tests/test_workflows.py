"""
Safety rules for the GitHub workflows in .github/workflows, checked on the text.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

WORKFLOW_DIRECTORY = Path(__file__).resolve().parents[1] / ".github" / "workflows"
WORKFLOW_PATHS = sorted(WORKFLOW_DIRECTORY.glob("*.yml"))
REUSABLE_WORKFLOW_PATHS = [
    path for path in WORKFLOW_PATHS if "workflow_call:" in path.read_text(encoding="utf-8")
]
USES_LINE = re.compile(r"^\s*(?:-\s+)?uses:\s*(?P<reference>\S+)(?P<comment>.*)$", re.MULTILINE)
PINNED_ACTION = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")
VERSION_COMMENT = re.compile(r"^\s+#\s+v[0-9]")


def list_run_blocks(workflow_text: str) -> list[str]:
    """
    The script of every `run: |` block: the lines indented deeper than the `run:` key.
    """
    run_blocks: list[str] = []
    lines = workflow_text.splitlines()
    for line_index, line in enumerate(lines):
        if line.strip() != "run: |":
            continue
        key_indent = len(line) - len(line.lstrip())
        block_lines: list[str] = []
        for block_line in lines[line_index + 1 :]:
            if block_line.strip() and len(block_line) - len(block_line.lstrip()) <= key_indent:
                break
            block_lines.append(block_line)
        run_blocks.append("\n".join(block_lines))
    return run_blocks


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
def test_run_blocks_never_expand_expressions(workflow_path):
    """
    What: the `run: |` scripts of a workflow.
    When: a step needs an input or event value.
    Then: it comes in through `env:`, never as `${{ }}` inside the script.
    """
    for run_block in list_run_blocks(workflow_path.read_text(encoding="utf-8")):
        assert "${{" not in run_block, run_block


@pytest.mark.parametrize("workflow_path", REUSABLE_WORKFLOW_PATHS, ids=lambda path: path.name)
def test_reusable_workflows_check_the_version_before_running_it(workflow_path):
    """
    What: a reusable workflow that runs devops-tools.
    When: the caller passes `devops-tools-version`.
    Then: a step rejects anything but a 40-character SHA before uvx installs that version.
    """
    workflow_text = workflow_path.read_text(encoding="utf-8")
    assert re.search(r"^      devops-tools-version:\n        description:", workflow_text, re.M)
    version_check_position = workflow_text.index("^[0-9a-f]{40}$")
    assert version_check_position < workflow_text.index("uvx --from")
    assert 'devops_tools@$DEVOPS_TOOLS_VERSION"' in workflow_text
