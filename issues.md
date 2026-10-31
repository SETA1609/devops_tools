# Issues

One issue is one pull request, on a branch named `issue-<n>-<slug>`. Numbers are never reused. Status is `todo`, `doing`, `review`, or `done`.

## Issue 1: Run logs and log pruning

- Status: review
- Do: Set up the package (uv, ruff, pytest, Python 3.13, standard library at runtime), `AGENTS.md`, `CHANGELOG.md`, and CI. Add the run log: every output line of a wrapped command gets a UTC timestamp and a stream tag (`out`, `err`, `run`) and goes to the terminal and to one log file per run, which ends with the command line, exit code, and duration. Add log pruning (all logs, or those older than N days, never the current run's). Add the `devops-tools` CLI with `run` and `prune-logs`.
- Done when: CI passes, and the README shows how a project wraps a command with a run log, from the CLI and from Python.
