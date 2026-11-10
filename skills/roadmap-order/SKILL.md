---
name: roadmap-order
description: >-
  Show which roadmap issues come first, which are ready and can run in
  parallel on separate branches or worktrees, which are blocked and by what,
  and the critical path, computed from the story files' Status and Needs
  lines and the owner's Focus line. Use when the user asks what to do next,
  what can run in parallel, what blocks an issue, or after changing an
  issue's Status or Needs (to regenerate the roadmap's story table).
allowed-tools: Bash, Read
---

# Roadmap order

`devops-tools roadmap-order` reads the story files (`stories-directory`), the per-issue files when `issues-directory` is set, the `Focus:` line (`focus-file`), and writes only the story table between the `<!-- roadmap-order begin … -->` and `<!-- roadmap-order end -->` markers in `roadmap-file`.

## How to run

From the repository root (add `--settings-file <path>` when the settings are not in the root `pyproject.toml`):

```sh
uvx --from "${CLAUDE_PLUGIN_ROOT}" devops-tools roadmap-order show    # issue view, changes nothing
uvx --from "${CLAUDE_PLUGIN_ROOT}" devops-tools roadmap-order write   # regenerate the story table
uvx --from "${CLAUDE_PLUGIN_ROOT}" devops-tools roadmap-order check   # exit 1 when the table is stale
```

## Keywords

| Keyword | Meaning |
|---|---|
| **first** | Ready and in a focus story; do these before anything else, in focus order. |
| **ready** | Every `Needs` is finished (`done` or `review`); can start now. |
| **wave N** | How many open issues stand in front of it. One wave can run in parallel once the earlier waves are merged. Wave 0 is ready. |
| **blocked by X** | Waits for the open issues (or stories) X. |
| **critical** | On the longest chain of open issues; a delay there delays everything after it. |

Two ready issues that list the same files will conflict; suggest running them one after the other. Run `write` in the same change that edits a `Status` or `Needs`.
