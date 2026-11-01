# devops_tools

Shared devops tooling for working with CI and containers, used by several repositories. Python 3.13, standard library only at runtime; a project needs only [uv](https://docs.astral.sh/uv/).

It has timestamped run logs, log pruning, and three repository workflow tools: open pull request rebasing, changelog fragments, and a submodule pin check. Planned: reusable GitHub workflows for those, the container runner, and agent skills as a Claude Code plugin. See `issues.md`.

## Install

Pin it to a commit in the project's `pyproject.toml`:

```toml
dependencies = ["devops-tools @ git+https://github.com/SETA1609/devops_tools@<40-char sha>"]
```

Or run it without installing: `uvx --from git+https://github.com/SETA1609/devops_tools@<sha> devops-tools ...`.

## Run logs

Every output line of a wrapped command gets a UTC timestamp (milliseconds) and a stream tag, and goes both to the terminal and to one log file per run:

- `out`: the command's stdout
- `err`: its stderr, or an error from the tool
- `run`: bookkeeping (command line, exit code, duration)

Log files are named `<utc-timestamp>-<name>.log`, so they sort by start time. Each ends with the command line, exit code, and duration. The tool exits with the command's exit code.

### From the command line

```sh
devops-tools run build -- make -j8
devops-tools --log-directory logs run test -- pytest
devops-tools prune-logs                       # remove every run log but this run's
devops-tools prune-logs --older-than-days 7   # only those older than a week
```

Logs go to `cache/logs/` under the current directory unless `--log-directory` comes first. Add that directory to `.gitignore`.

### From Python

A project CLI wraps its own subcommands the same way:

```python
import functools
import sys
from pathlib import Path

from devops_tools.run_log import RunLog, run_command_with_timestamped_output, run_with_run_log


def build_image(image_tag: str, run_log: RunLog) -> int:
    run_log.write_line("run", f"building {image_tag}")
    return run_command_with_timestamped_output(
        ["docker", "build", "--tag", image_tag, "."], run_log
    )


exit_code = run_with_run_log(
    Path("cache/logs"),
    "image",
    ["example", "image"],
    functools.partial(build_image, "example:latest"),
)
sys.exit(exit_code)
```

Pruning is in `devops_tools.run_log_cleanup`: `select_run_log_files_to_remove` returns the `*.log` files directly in the directory that are old enough, and never other files, subdirectories, symlinks, or the current run's log.

## Repository workflow

These print plain output for CI; wrap one in `devops-tools run <name> -- ...` to log it.

| Subcommand | What it does |
|---|---|
| `rebase-open-branches` | Rebases each open pull request from this repository onto the main branch and pushes with `--force-with-lease`. A changelog conflict where both sides only added lines keeps both, the branch's entries first, with the newer `Last updated:` timestamp. Any other conflict leaves that branch for a person. Needs `GITHUB_REPOSITORY` and `GITHUB_TOKEN`, or `--branches NAME...` to run locally. |
| `changelog-fragments check [--branch B]` | Each pull request adds `changes/<issue-id>.md` instead of editing the changelog. Checks every fragment, and with `--branch` that the branch's issue has one. |
| `changelog-fragments preview` | Prints the unreleased entries, newest first. |
| `changelog-fragments release --section-title T` | Moves the fragments into the changelog under `## T`, with `(#N)` from squash merge subjects, and deletes them. |
| `check-submodule-pins [--json]` | Checks that every submodule pointer is a commit on its upstream branch, not only on a pull request ref. Suggests a commit on the branch with the same tree. |

All three take `--repository PATH` (default: the current directory) and `--settings-file PATH`.

### Settings

A project sets them in a `[tool.devops-tools]` table, read from `<repository>/pyproject.toml` or from `--settings-file`. Every key is optional; unknown keys are an error.

```toml
[tool.devops-tools]
main-branch = "main"                                       # rebase target
issue-id-pattern = '[A-Za-z][A-Za-z0-9]*(?:\.[0-9]+)?-[0-9]+'  # one issue ID, no anchors
changes-directory = "changes"                              # fragments
changelog-file = "CHANGELOG.md"                            # fragments and the rebase merge driver
```

Branch names are `<issue-id>-<slug>` or `agent/<agent-name>/<issue-id>-<slug>`, matched ignoring case.

## Development

```sh
uv run pytest
uv run ruff check
uv run ruff format --check
```

Contributor rules are in `AGENTS.md`. MIT licence.
