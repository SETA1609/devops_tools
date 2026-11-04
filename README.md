# devops_tools

Shared devops tooling for working with CI and containers, used by several repositories. Python 3.13, standard library only at runtime; a project needs only [uv](https://docs.astral.sh/uv/).

It has timestamped run logs, log pruning, and three repository workflow tools: open pull request rebasing, changelog fragments, and a submodule pin check. Each has a reusable GitHub workflow. It also runs a project's toolchain container. Planned: the agent container. See `issues.md`.

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
| `rebase-open-branches` | Rebases each open pull request from this repository onto the main branch and pushes with `--force-with-lease`. A changelog conflict where both sides only added lines keeps both, the branch's entries first, with the newer `Last updated:` timestamp. Files matching `keep-both-added-lines` get the same merge. With `regenerate-roadmap-on-rebase`, the generated story table in `roadmap-file` is never merged line by line: the rebase takes the main branch's table, merges the rest of the file as usual, then regenerates the table from the rebased story files and commits it when it changed (`Regenerate the roadmap order table`), so two pull requests that change issue statuses neither conflict nor leave a stale count. Any other conflict leaves that branch for a person. A branch whose every change is already in the main branch (squash merged, then pushed again) is skipped, and a local branch checked out in another worktree is never moved. Needs `GITHUB_REPOSITORY` and `GITHUB_TOKEN`, or `--branches NAME...` to run locally. |
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
keep-both-added-lines = ["docs/stories/*.md"]             # more files the rebase merges like the changelog
regenerate-roadmap-on-rebase = true                        # rebuild the roadmap story table when rebasing
```

Branch names are `<issue-id>-<slug>` or `agent/<agent-name>/<issue-id>-<slug>`, matched ignoring case.

### Reusable workflows

A project calls them with a few lines, pinning the workflow and the tool to the same commit (the release tag goes in a comment). `devops-tools-version` must be the full 40-character SHA; anything else fails before uv installs it. `settings-file` is optional and defaults to the root `pyproject.toml`.

```yaml
# .github/workflows/rebase-open-branches.yml
name: Rebase open branches
on:
  push:
    branches: [main]
permissions:
  contents: write
  pull-requests: read
concurrency:
  group: rebase-open-branches
  cancel-in-progress: false
jobs:
  rebase-open-branches:
    uses: SETA1609/devops_tools/.github/workflows/rebase-open-branches.yml@<sha> # v0.3.0
    with:
      devops-tools-version: <sha>
      settings-file: tools/pyproject.toml
```

```yaml
# .github/workflows/changelog-fragments.yml
name: Changelog fragments
on:
  pull_request:
    branches: [main]
permissions:
  contents: read
jobs:
  check-changelog-fragments:
    uses: SETA1609/devops_tools/.github/workflows/changelog-fragments.yml@<sha> # v0.3.0
    with:
      devops-tools-version: <sha>
```

```yaml
# .github/workflows/submodule-pins.yml
name: Submodule pins
on:
  pull_request:
    branches: [main]
    paths: [.gitmodules, libs/**]
  push:
    branches: [main]
    paths: [.gitmodules, libs/**]
permissions:
  contents: read
jobs:
  check-submodule-pins:
    uses: SETA1609/devops_tools/.github/workflows/submodule-pins.yml@<sha> # v0.3.0
    with:
      devops-tools-version: <sha>
```

The caller's `permissions` are the most a reusable workflow gets. Pushes the rebase makes with `GITHUB_TOKEN` do not trigger other workflows.

## Toolchain container

`devops-tools container [--repository PATH] [--settings-file PATH] <action> [args...]` runs the project's toolchain image as its `[tool.devops-tools.container]` table describes. Every run is logged to `cache/logs/` like `run`. The repository defaults to the git top level of the current directory.

| Action | What it does |
|---|---|
| `image` | Build the image (checking the toolchain version first), prune dangling layers and build cache, print its id and size. |
| `<name> [--keep-cache] [args...]` | Run a command named in `[tool.devops-tools.container.commands]`, with the extra arguments appended. Builds the image first if it is missing. |
| `exec [--keep-cache] [--] <command...>` | Run any command in the container. |
| `shell [--keep-cache]` | An interactive bash in the container. |
| `agent [--keep-cache] [--rebuild-image] [command...]` | The agent container (see below); `bash` by default. |
| `prune` | Remove dangling images and unused build cache. Tagged images and volumes stay. |
| `clean` | End of work only: remove `clean-directories`, the cache volume, then prune. Refuses symlinks, paths outside the checkout, and `protected-directories`. |

### Images: a shared base, the project's toolchain on top

The package ships `devops-tools-base`: Ubuntu with git, python3, uv, and a uv-managed Python 3.13, which is everything the shared tooling needs, and no language toolchain. The runner builds it locally (tag `devops-tools-base:<package version>-<content hash>`, so a changed base is rebuilt) and passes it to the project build as `BASE_IMAGE`. A project's Dockerfile adds only its own tools, for any language:

```dockerfile
ARG BASE_IMAGE
FROM ${BASE_IMAGE}
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc g++ cmake openjdk-21-jdk-headless golang \
    && rm -rf /var/lib/apt/lists/*
```

Download stages may start from anything; the stage that is run must be `FROM ${BASE_IMAGE}`. The runner refuses a Dockerfile without `ARG BASE_IMAGE` and that stage. The base image's entrypoint makes sure `HOME` exists and runs the command (`bash` by default), so a project image needs no entrypoint of its own.

### Agent container

`agent` runs the shipped agent image: the project image plus Node, Claude Code, and an `agent` user with the host's uid and gid. No project keeps its own agent Dockerfile. The home is a named volume (`agent-home-volume`, default `personal-agent-home`; `AGENT_HOME_VOLUME` overrides), so the agent's Claude login and git identity survive the container and never touch the host's. Nothing from the host's `~/.claude`, `~/.gitconfig`, or SSH keys is mounted, so the agent can commit but not push.

On every start, before the command, a start script installs what the project declares and is missing, so a fresh volume needs no manual step:

1. each marketplace in `.claude/settings.json` `extraKnownMarketplaces` that is not known yet (`claude plugin marketplace add owner/repo#ref`),
2. each plugin set to `true` in `enabledPlugins` that is not installed (`claude plugin install`, user scope, kept in the volume),
3. each command in `agent-setup-commands`, run in the checkout.

A failed step is reported, the command still starts, and the step is tried again next start. With nothing missing, a start only runs the setup commands.

```toml
[tool.devops-tools.container]
agent-home-volume = "personal-agent-home"     # default
agent-setup-commands = [["uv", "sync", "--project", "tools"]]
agent-claude-code-version = "2.1.316"         # default: the agent Dockerfile's pin
```

The container runs as the host user (`CONTAINER_AS_ROOT=1` opts out) with a throwaway home. The checkout is mounted at its host path, and so is its git directory when that lives outside (a linked worktree, a submodule), so git works inside the container from any checkout. `IMAGE` overrides the image tag.

```toml
[tool.devops-tools.container]
image = "example"                         # required; the tag is added
dockerfile = "container/Dockerfile"       # default
toolchain = "zig"                         # tag is example:zig-<version>
version-file = ".zig-version"             # with version-argument: checked against
version-argument = "ZIG_VERSION"          #   the Dockerfile's ARG and passed as --build-arg
version-pins = [{ file = ".devcontainer/devcontainer.json", pattern = 'example:zig-([0-9.]+)' }]
cache-environment-variable = "ZIG_GLOBAL_CACHE_DIR"  # throwaway under the home by default
cache-volume = "example-zig-cache"        # used with --keep-cache
read-only-symlink-mounts = ["references/data"]       # symlink targets mounted read-only
clean-directories = ["zig-out", ".zig-cache"]
protected-directories = ["references", "cache/logs"] # default: ["cache/logs"]

[tool.devops-tools.container.commands]
build = ["zig", "build"]
test = ["zig", "build", "test"]
```

A wrapper script is one line: `exec uv run --project tools devops-tools container --settings-file tools/pyproject.toml build "$@"`.

## Claude Code plugin

This repository is also a Claude Code plugin marketplace, `devops-tools`, whose one plugin, `devops-tools`, is the repository root. It ships three skills, each a thin guide around a subcommand:

| Skill | Runs | Use |
|---|---|---|
| `/devops-tools:status-report` | `devops-tools status-report` | Where the work stands: branches against main (squash merges included), worktrees, pull requests, submodules, story issues in `doing` or `review`, the next `todo` per story, with suggested actions. Changes nothing. |
| `/devops-tools:roadmap-order` | `devops-tools roadmap-order show\|write\|check` | `first`, `ready`, `wave N`, `blocked by`, and `critical` for every open issue, from its `Status` and `Needs` lines and the `Focus:` line; `write` regenerates the story table between `<!-- roadmap-order begin … -->` and `<!-- roadmap-order end -->`. |
| `/devops-tools:fetch-docs` | `devops-tools fetch-docs url\|github\|vulkan-spec\|list` | Downloads docs, specs, and sources into the gitignored docs cache, pinned to a commit, to read and quote them exactly. |

A skill runs `uvx --from "${CLAUDE_PLUGIN_ROOT}" devops-tools <subcommand>`: Claude Code substitutes the plugin's installed path into the skill text, and that path is this repository at the installed version, so the skill always runs the code it shipped with. The machine needs only uv. [V 2026-11-01: `${CLAUDE_PLUGIN_ROOT}` is substituted anywhere in a skill's Markdown body and is not set in the Bash tool's environment (code.claude.com plugin manifest reference); a plugin entry may use `"./"`, the marketplace root, as its source (marketplace reference); `claude plugin validate` passes; the plugin installs from a local marketplace and lists its three skills (Claude Code 2.1.316).]

A project enables it in `.claude/settings.json`, pinning a release tag (a marketplace source takes a `ref`, not a `sha`; tags are never moved):

```json
{
  "extraKnownMarketplaces": {
    "devops-tools": {
      "source": { "source": "github", "repo": "SETA1609/devops_tools", "ref": "v0.3.0" }
    }
  },
  "enabledPlugins": { "devops-tools@devops-tools": true }
}
```

The skills read these `[tool.devops-tools]` keys, all optional:

```toml
[tool.devops-tools]
stories-directory = "docs/stories"           # one Markdown file per story track, plus done.md
roadmap-file = "docs/roadmap.md"             # gets the generated story table
focus-file = "docs/stories/README.md"        # holds the `Focus: AB, CD` line
docs-cache-directory = "cache/docs"          # fetch-docs downloads, gitignore it
```

[U] Whether a fresh agent container installs the plugin without a manual step depends on its start script (Issue 7).

## Releases

Releases are tags `vX.Y.Z` on `main` (semantic versioning), each with a `## vX.Y.Z` section in `CHANGELOG.md`. Tags are never moved or deleted. Projects pin the commit SHA and name the tag in a comment.

## Development

```sh
uv run pytest
uv run ruff check
uv run ruff format --check
```

Contributor rules are in `AGENTS.md`. MIT licence.
