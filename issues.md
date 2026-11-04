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

- Status: done
- Do: Reusable GitHub workflows (`workflow_call`) for the three subcommands, installing uv with a pinned `astral-sh/setup-uv` and running `devops-tools` from a commit given by the caller. A caller workflow is a few lines.
- Done when: each workflow passes a workflow lint and `tests/test_workflows.py`, and the README shows a caller for each.

## Issue 5: What/When/Then docstrings on every test

- Status: todo
- Do: Give every existing test function a docstring with `What:`, `When:`, and `Then:` lines (rule in `AGENTS.md`). Add a test that fails when a test function lacks one.
- Done when: every test has the docstring and the new check passes.

## Issue 6: Toolchain container runner

- Status: done
- Do: Run a project's toolchain image from a `[tool.devops-tools.container]` table: build it with a checked toolchain version, run named commands and any command as the host user with a throwaway home and an opt-in cache volume, open a shell, prune, and clean build directories. Mount the checkout at its host path, and its git directory when that lives outside.
- Done when: the runner is covered with a fake docker, and a real run of a project's toolchain image works from the main checkout and from a linked worktree.

## Issue 7: Agent container with a start script

- Status: done
- Needs: Issue 8.
- Do: `devops-tools container agent [command...]` builds the shipped agent image (Node, Claude Code, an agent user with the host's ids) on the project's toolchain image, so no project needs its own agent Dockerfile, and runs it with the home in a named volume (`personal-agent-home` by default), so the agent's logins survive and never touch the host's. Before the command, a start script installs what the project declares and is missing: the marketplaces and plugins in `.claude/settings.json` (`claude plugin marketplace add`, `claude plugin install`) and the setup commands in the settings (for example `uv sync`).
- Done when: the start script is covered with a fake `claude`, and a real agent container installs a declared plugin on first start with no manual step.

## Issue 8: Shared base image

- Status: done
- Do: Ship a base image with what the shared tooling needs (git, python3, uv, a uv-managed Python 3.13, an entrypoint) and no language toolchain. Build it locally and pass it to the project build as `BASE_IMAGE`; refuse a project Dockerfile that does not build on it. Projects add only their own toolchain on top.
- Done when: a project image for another language (C) builds on the base, compiles in it, and runs uv, git, and `devops-tools` inside as the host user.

## Issue 9: Ship the skills as a Claude Code plugin

- Status: done
- Do: Move the status report, the roadmap order keywords, and docs fetching into the package as `devops-tools status-report`, `roadmap-order`, and `fetch-docs`, reading project paths from the settings. Make this repository a Claude Code marketplace whose one plugin is the repository root, with one skill per subcommand.
- Done when: the moved tests pass with neutral fixtures, `claude plugin validate` passes, and the plugin installs from a marketplace and lists its skills.


## Issue 10: Regenerate the roadmap table when rebasing

- Status: review
- Do: The story table between the roadmap markers is generated, and every pull request that changes an issue's status regenerates it, so two open pull requests edit the same rows. Rebasing one onto the other either stops on a conflict a person has to resolve by hand, or merges cleanly and leaves a stale table (a wrong open-issue count). Add the opt-in setting `regenerate-roadmap-on-rebase`. With it, `rebase-open-branches` routes the roadmap file to a merge driver that ignores the generated block (it takes the target's block and merges the rest of the file as usual, so a conflict outside the block still stops), and after each successful rebase it regenerates the table from the rebased story files and commits the result when it changed.
- Done when: tests cover a conflict inside the block (resolved, table correct), a clean merge that left the table stale (a regeneration commit), a conflict outside the block (left for a person), the setting off (old behaviour), and the setting's parsing.
- Review 2026-11-04: `uv run pytest` passes (337, of which 11 are new in `tests/test_rebase_regenerates_roadmap.py`); `ruff check` and `ruff format --check` pass. The stale-table case is the common one: two branches that each mark a different issue of the same story finished produce the identical row change, which git merges cleanly into a wrong count. The regeneration commit is made with whatever identity the rebase runs under (the Actions bot in CI). Not run in a real workflow yet.
