# Changelog

Newest first. Each entry names its issue from `issues.md`.

## Unreleased

### Issue 1: Run logs and log pruning

- Package `devops-tools` (import `devops_tools`), standard library only at runtime; uv, ruff, and pytest for development; CI runs tests, lint, and the format check.
- Run log: every output line of a wrapped command gets a UTC timestamp and a stream tag (`out`, `err`, `run`) and goes to the terminal and one log file per run, which ends with the command line, exit code, and duration. `run_with_run_log` wraps a project's own subcommand the same way.
- Log pruning: all run logs, or those older than N days; never other files, subdirectories, symlinks, or the current run's log.
- CLI: `devops-tools [--log-directory DIR] run <name> [--] <command...>` and `prune-logs [--older-than-days N]`.
