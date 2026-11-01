# Changelog

Newest first. Each entry names its issue from `issues.md`.

## Unreleased

### Issue 4: Reusable workflows

- Reusable workflows `rebase-open-branches.yml`, `changelog-fragments.yml`, and `submodule-pins.yml` (`workflow_call`). Each takes `devops-tools-version` (a full commit SHA, checked before use) and, where settings apply, `settings-file`, installs uv with a pinned `astral-sh/setup-uv`, and runs `uvx --from git+…@<sha> devops-tools …`.
- `tests/test_workflows.py`: every action is pinned to a SHA with a version comment, every workflow declares its permissions, no `${{ }}` inside `run:` scripts, and the reusable workflows check the version first.
- Contributor rules: release tags `vX.Y.Z`, and What/When/Then docstrings on every test.

### Issue 3: Rebase fixes for squash merges, worktrees, and added lines

- `rebase-open-branches` skips a branch whose every changed file already has the branch's content in the main branch, as after a squash merge, instead of replaying it into conflicts.
- It never moves a local branch that is checked out in another worktree; it says which worktree.
- Setting `keep-both-added-lines`: a list of gitattributes patterns whose added-lines conflicts are resolved like the changelog's, both sides kept, the branch's first.

### Issue 2: Move the repository workflow scripts

- Settings: a `[tool.devops-tools]` table in `pyproject.toml` (or `--settings-file`) sets the main branch, the issue ID pattern, the changes directory, and the changelog file. Unknown keys and bad patterns are errors.
- `devops-tools rebase-open-branches`: rebases open pull requests onto the main branch and pushes with `--force-with-lease`; keeps both sides of a changelog conflict where both only added lines. Git runs the merge driver as `python -I -m devops_tools.rebase_open_branches`, so it works from a uvx install.
- `devops-tools changelog-fragments check|preview|release`: one fragment per issue, moved into the changelog at a release. Branch names match the issue ID pattern ignoring case.
- `devops-tools check-submodule-pins`: every submodule pin must be a commit on its upstream branch.

### Issue 1: Run logs and log pruning

- Package `devops-tools` (import `devops_tools`), standard library only at runtime; uv, ruff, and pytest for development; CI runs tests, lint, and the format check.
- Run log: every output line of a wrapped command gets a UTC timestamp and a stream tag (`out`, `err`, `run`) and goes to the terminal and one log file per run, which ends with the command line, exit code, and duration. `run_with_run_log` wraps a project's own subcommand the same way.
- Log pruning: all run logs, or those older than N days; never other files, subdirectories, symlinks, or the current run's log.
- CLI: `devops-tools [--log-directory DIR] run <name> [--] <command...>` and `prune-logs [--older-than-days N]`.
