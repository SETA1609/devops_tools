# Changelog

Newest first. Each entry names its issue from `issues.md`.

## Unreleased

### Issue 7: Agent container with a start script

- `devops-tools container agent [--keep-cache] [--rebuild-image] [command...]` builds the shipped agent image (Node, Claude Code, an `agent` user with the host's ids) on the project image and runs it with the home in a named volume (`personal-agent-home` by default).
- Its start script installs, on every start, the marketplaces and enabled plugins from `.claude/settings.json` that are missing (`claude plugin marketplace add owner/repo#ref`, `claude plugin install`), then runs `agent-setup-commands`; a failed step is reported and retried next start.
- Settings `agent-home-volume`, `agent-setup-commands`, `agent-claude-code-version`. The shipped images now live in `container_images/base/` and `container_images/agent/`, each tagged by its own content hash.

### Issue 8: Shared base image

- The package ships `devops-tools-base` (Ubuntu, git, python3, uv, a uv-managed Python 3.13, and an entrypoint) and no language toolchain. `devops-tools container` builds it locally, tagged with the package version and a content hash, and passes it to the project build as `BASE_IMAGE`; `image` always rebuilds it.
- A project Dockerfile must declare `ARG BASE_IMAGE` and build its final stage `FROM ${BASE_IMAGE}`, adding only its own toolchain (C, C++, Java, Go, Zig, ...). The runner refuses one that does not.

### Issue 6: Toolchain container runner

- `devops-tools container <action>`: `image`, `exec`, `shell`, `prune`, `clean`, and commands named in `[tool.devops-tools.container.commands]`, each logged to `cache/logs/`.
- Settings table `[tool.devops-tools.container]`: image name, Dockerfile, toolchain version file checked against the Dockerfile's `ARG` and extra `version-pins`, cache variable and opt-in cache volume (`--keep-cache`), read-only symlink mounts, clean and protected directories.
- The checkout is mounted at its host path, with its git directory when that lives outside (worktrees, submodules), and `safe.directory` set for it.

## v0.1.0 (2026-11-01)

First release: run logs, log pruning, the three repository workflow tools with settings, and their reusable workflows.

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
