---
name: status-report
description: >-
  Report where the work in this repository stands: local branches against
  origin/main (ahead, behind, remote gone, already merged even after a squash
  merge), worktrees with uncommitted changes, open pull requests, submodules
  off their pin or off upstream main, story issues in doing or review (flagged
  when already merged), and the next todo issue per story file, with suggested
  actions. Use at the start of a session, when the user asks "where were we",
  what is open, which branches or pull requests are left, or before cleaning
  up branches or worktrees. It changes nothing.
allowed-tools: Bash, Read
---

# Status report

`devops-tools status-report` reads git and the story files and prints one report. It fetches `origin` with `--prune` first; nothing else is written. Paths and the issue ID pattern come from the project's `[tool.devops-tools]` settings.

## How to run

From the repository root (pass `--settings-file <path>` when the project's `[tool.devops-tools]` table is not in the root `pyproject.toml`):

```sh
uvx --from "${CLAUDE_PLUGIN_ROOT}" devops-tools status-report              # text
uvx --from "${CLAUDE_PLUGIN_ROOT}" devops-tools status-report --json       # for parsing
uvx --from "${CLAUDE_PLUGIN_ROOT}" devops-tools status-report --no-fetch   # offline
```

## Reading the report

- **Branches.** `upstream gone` means the remote branch was deleted, usually after its pull request merged. `already in main` means main has the branch's changes: it is an ancestor, a main commit has its tree or its combined patch (a squash merge), or every file it changed is identical in main. `merged in #N` means a main commit names the branch's issue with `(#N)`, which catches a squash merge of a version rebased after the local copy. A gone branch with neither may hold unmerged work.
- **Pull requests.** With `gh` installed and logged in: the open pull requests. Without it: `refs/pull/N/head` refs whose head is still a branch tip on origin, so probably open; closed pull requests whose branch still exists also match.
- **Submodules.** `not_at_pin` means the checkout differs from the pointer; `git submodule update --init --recursive` fixes it. Pins that are not on their upstream branch are listed too (only with a fetch).
- **Story issues.** Issues in `doing` or `review`, then the first `todo` of each story file. `merged in #N` on an active issue means its story file still needs the move to `done.md`.

## Suggested actions

The report ends with commands and steps. Do not run them on your own: deleting branches or worktrees, pushing, and closing pull requests need the user's go-ahead. Show the user the list, say which ones you recommend, and run only what they confirm. Check a branch flagged "check before deleting" with `git log origin/main..<branch>` first.
