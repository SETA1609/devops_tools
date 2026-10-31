# devops_tools

Shared devops tooling for several repositories: timestamped run logs and log pruning, and later the container runner, repository workflow scripts, and agent skills. Projects pin it to a commit (`devops-tools @ git+https://github.com/SETA1609/devops_tools@<sha>`) and keep their own configuration and project-only subcommands.

## Rules

- This repository never names a project that uses it, in code, docs, changelog, or commits. Examples use neutral names.
- Runtime code uses the Python standard library only. Development uses uv, ruff, and pytest.
- Work is tracked in `issues.md` (`Issue N`). One issue is one pull request on a branch `issue-<n>-<slug>`, with at most 20 changed files (files with 5 or fewer changed lines do not count). Each pull request adds its entry to `CHANGELOG.md` under `Unreleased`.
- Commit only when the owner asks. Merging to `main` needs the owner. Do not force-push or rewrite published history.
- Pin every GitHub Action to a full commit SHA with the version in a comment.

## Code style

- Names are verbose and descriptive: verb + object for functions, spelled-out words, units in names (`duration_seconds`). No invented abbreviations, dropped vowels, or single letters outside short loop counters.
- Docstrings put `"""` on their own lines and have no blank lines inside.
- `constants.py` holds constants, `exceptions.py` exceptions, `models.py` only types (dataclasses, aliases).
- Line length 100, Python 3.13.

## Checks

```sh
uv run pytest
uv run ruff check
uv run ruff format --check
```
