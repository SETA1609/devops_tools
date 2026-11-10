# devops_tools

Shared devops tooling for several repositories: timestamped run logs and log pruning, and later the container runner, repository workflow scripts, and agent skills. Projects pin it to a commit (`devops-tools @ git+https://github.com/SETA1609/devops_tools@<sha>`) and keep their own configuration and project-only subcommands.

## Rules

- This repository never names a project that uses it, in code, docs, changelog, or commits. Examples use neutral names.
- Runtime code uses the Python standard library only. Development uses uv, ruff, and pytest.
- Work is tracked in `issues.md` (`Issue N`). One issue is one pull request on a branch `issue-<n>-<slug>`, with at most 20 changed files (files with 5 or fewer changed lines do not count). Each pull request adds its entry to `CHANGELOG.md` under `Unreleased`.
- Commit only when the owner asks. Merging to `main` needs the owner. Do not force-push or rewrite published history.
- Pin every GitHub Action to a full commit SHA with the version in a comment. A workflow `run:` step is one call of a committed script in `scripts/workflows/`, never inline scripting; a reusable workflow checks this repository out at the pinned commit to reach it. Scripts get inputs and event values through `env:`, never as `${{ }}`. `tests/test_workflows.py` checks all of this.
- Releases are tags `vX.Y.Z` on `main`. Cutting one: move the `Unreleased` entries under `## vX.Y.Z`, merge that, then tag the merge commit. Tags are never moved or deleted. Pushing a tag needs the owner.

## Code style

- Names are verbose and descriptive: verb + object for functions, spelled-out words, units in names (`duration_seconds`). No invented abbreviations, dropped vowels, or single letters outside short loop counters.
- Docstrings put `"""` on their own lines and have no blank lines inside.
- `constants.py` holds constants, `exceptions.py` exceptions, `models.py` only types (dataclasses, aliases).
- Line length 100, Python 3.13.
- Every test function has a docstring with `What:` (the unit or behaviour under test), `When:` (the situation), and `Then:` (the expected outcome), one line each:

```python
def test_rebase_skips_a_branch_whose_changes_are_already_in_the_target(tmp_path):
    """
    What: rebase-open-branches.
    When: every file the branch changed already has the branch's content in the main branch.
    Then: the branch is left unchanged and the run still succeeds.
    """
```

## Checks

```sh
uv run pytest
uv run ruff check
uv run ruff format --check
```
