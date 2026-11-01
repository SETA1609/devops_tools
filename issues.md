# Issues

One issue is one pull request, on a branch named `issue-<n>-<slug>`. Numbers are never reused. Status is `todo`, `doing`, `review`, or `done`.

## Issue 1: Run logs and log pruning

- Status: done
- Do: Set up the package (uv, ruff, pytest, Python 3.13, standard library at runtime), `AGENTS.md`, `CHANGELOG.md`, and CI. Add the run log: every output line of a wrapped command gets a UTC timestamp and a stream tag (`out`, `err`, `run`) and goes to the terminal and to one log file per run, which ends with the command line, exit code, and duration. Add log pruning (all logs, or those older than N days, never the current run's). Add the `devops-tools` CLI with `run` and `prune-logs`.
- Done when: CI passes, and the README shows how a project wraps a command with a run log, from the CLI and from Python.

## Issue 2: Move the repository workflow scripts

- Status: done
- Do: Add the three repository workflow tools as `devops-tools` subcommands, with their tests: `rebase-open-branches` (rebase each open pull request onto the main branch and push with `--force-with-lease`, keeping both sides of a `CHANGELOG.md` conflict where both only added lines), `changelog-fragments` (one `changes/<issue-id>.md` per pull request, moved into `CHANGELOG.md` at a release), and `check-submodule-pins` (every submodule pointer is a commit on its upstream branch). Read the main branch, the issue ID pattern, the changes directory, and the changelog file from a `[tool.devops-tools]` table in `pyproject.toml`.
- Done when: the three subcommands pass their tests with default and project settings, and the README documents the settings table.

## Issue 3: Rebase fixes for squash merges, worktrees, and added lines

- Status: done
- Do: `rebase-open-branches` skips a branch whose changes are already in the main branch (squash merged, then pushed again); never moves a local branch that is checked out in another worktree; and keeps both sides when two branches only add lines at the same place in any file matching a pattern in the `keep-both-added-lines` setting, not only the changelog.
- Done when: a test covers each case.

## Issue 4: Reusable workflows

- Status: review
- Do: Reusable GitHub workflows (`workflow_call`) for the three subcommands, installing uv with a pinned `astral-sh/setup-uv` and running `devops-tools` from a commit given by the caller. A caller workflow is a few lines.
- Done when: each workflow passes a workflow lint and `tests/test_workflows.py`, and the README shows a caller for each.

## Issue 5: What/When/Then docstrings on every test

- Status: todo
- Do: Give every existing test function a docstring with `What:`, `When:`, and `Then:` lines (rule in `AGENTS.md`). Add a test that fails when a test function lacks one.
- Done when: every test has the docstring and the new check passes.
