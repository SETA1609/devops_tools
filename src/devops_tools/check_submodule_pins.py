"""
Check that every submodule pointer is a commit on its upstream branch.
A pin that is only on a pull request ref (the head of a pull request that was later squash
merged) clones only as long as the host keeps that ref. Each submodule's upstream branch, the
`branch =` in .gitmodules or else the remote's default branch, is fetched without blobs into a
temporary bare repository, so the submodule checkouts are never touched.
    devops-tools check-submodule-pins [--repository PATH] [--json]
Statuses: on_branch (fine), not_on_branch (names the commit on the branch with the same tree,
if any), missing_on_remote, fetch_failed. Exits 1 unless every pin is on_branch.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from devops_tools.constants import (
    GIT_TIMEOUT_SECONDS,
    GITLINK_MODE,
    SHORT_COMMIT_LENGTH,
    STATUS_FETCH_FAILED,
    STATUS_MISSING_ON_REMOTE,
    STATUS_NOT_ON_BRANCH,
    STATUS_ON_BRANCH,
    UPSTREAM_BRANCH_REFERENCE,
    UPSTREAM_REMOTE_NAME,
)
from devops_tools.models import SubmodulePin, SubmodulePinCheck


def list_submodule_pins(repository: Path) -> list[SubmodulePin]:
    """
    Gitlinks in HEAD's tree, with url and branch from HEAD's .gitmodules, sorted by path.
    """
    tree_listing = run_git(repository, "ls-tree", "-r", "-z", "HEAD")
    if tree_listing.returncode != 0:
        raise RuntimeError(tree_listing.stderr.strip() or "git ls-tree HEAD failed")
    pinned_commit_by_path: dict[str, str] = {}
    for entry in tree_listing.stdout.split("\0"):
        if not entry:
            continue
        object_description, _, path = entry.partition("\t")
        mode, _, object_sha = object_description.split(" ", 2)
        if mode == GITLINK_MODE:
            pinned_commit_by_path[path] = object_sha
    if not pinned_commit_by_path:
        return []
    settings = run_git(
        repository,
        "config",
        "--blob",
        "HEAD:.gitmodules",
        "--get-regexp",
        r"^submodule\..*\.(path|url|branch)$",
    )
    fields_by_name: dict[str, dict[str, str]] = {}
    for line in settings.stdout.splitlines():
        key, _, value = line.partition(" ")
        name, _, field = key.removeprefix("submodule.").rpartition(".")
        fields_by_name.setdefault(name, {})[field] = value
    fields_by_path = {
        fields["path"]: fields for fields in fields_by_name.values() if "path" in fields
    }
    pins: list[SubmodulePin] = []
    for path, pinned_commit in sorted(pinned_commit_by_path.items()):
        fields = fields_by_path.get(path, {})
        pins.append(
            SubmodulePin(
                path=path,
                url=fields.get("url", ""),
                pinned_commit=pinned_commit,
                branch=fields.get("branch"),
            )
        )
    return pins


def find_remote_default_branch(url: str) -> str | None:
    """
    The branch the remote's HEAD points at (`main`), or None if it cannot be read.
    """
    completed = run_git(None, "ls-remote", "--symref", url, "HEAD")
    if completed.returncode != 0:
        return None
    for line in completed.stdout.splitlines():
        if line.startswith("ref: refs/heads/") and line.endswith("\tHEAD"):
            return line.removeprefix("ref: refs/heads/").removesuffix("\tHEAD")
    return None


def find_commit_with_same_tree(
    bare_repository: Path, tree_sha: str, branch_reference: str
) -> str | None:
    """
    The newest commit on branch_reference whose tree is tree_sha.
    """
    completed = run_git(bare_repository, "log", "--format=%H %T", branch_reference)
    for line in completed.stdout.splitlines():
        commit_sha, _, commit_tree_sha = line.partition(" ")
        if commit_tree_sha == tree_sha:
            return commit_sha
    return None


def check_submodule_pin(pin: SubmodulePin, work_directory: Path) -> SubmodulePinCheck:
    """
    Fetch the pin's upstream branch into a bare repository under work_directory and
    classify the pin.
    """
    short_pin = pin.pinned_commit[:SHORT_COMMIT_LENGTH]

    def result(
        status: str, message: str, branch: str | None, suggested_commit: str | None = None
    ) -> SubmodulePinCheck:
        return SubmodulePinCheck(
            path=pin.path,
            url=pin.url,
            pinned_commit=pin.pinned_commit,
            branch=branch,
            status=status,
            suggested_commit=suggested_commit,
            message=f"{pin.path}: {message}",
        )

    if not pin.url:
        return result(STATUS_FETCH_FAILED, "no url in .gitmodules", pin.branch)
    branch = pin.branch or find_remote_default_branch(pin.url)
    if branch is None:
        return result(STATUS_FETCH_FAILED, f"cannot read the default branch of {pin.url}", None)
    bare_repository = work_directory / "upstream.git"
    run_git(None, "init", "--quiet", "--bare", str(bare_repository))
    run_git(bare_repository, "remote", "add", UPSTREAM_REMOTE_NAME, pin.url)
    branch_fetch = fetch_without_blobs(
        bare_repository, f"+refs/heads/{branch}:{UPSTREAM_BRANCH_REFERENCE}"
    )
    if branch_fetch.returncode != 0:
        error_line = last_line(branch_fetch.stderr)
        return result(
            STATUS_FETCH_FAILED, f"cannot fetch {branch} from {pin.url}: {error_line}", branch
        )
    ancestor_check = run_git(
        bare_repository, "merge-base", "--is-ancestor", pin.pinned_commit, UPSTREAM_BRANCH_REFERENCE
    )
    if ancestor_check.returncode == 0:
        return result(STATUS_ON_BRANCH, f"{short_pin} is on {branch}", branch)
    if fetch_without_blobs(bare_repository, pin.pinned_commit).returncode != 0:
        return result(STATUS_MISSING_ON_REMOTE, f"{short_pin} is not on {pin.url} at all", branch)
    tree_sha = run_git(bare_repository, "rev-parse", f"{pin.pinned_commit}^{{tree}}").stdout.strip()
    suggested_commit = find_commit_with_same_tree(
        bare_repository, tree_sha, UPSTREAM_BRANCH_REFERENCE
    )
    if suggested_commit is None:
        return result(
            STATUS_NOT_ON_BRANCH,
            f"{short_pin} is not on {branch}; merge it upstream, then pin the merged commit",
            branch,
        )
    short_suggestion = suggested_commit[:SHORT_COMMIT_LENGTH]
    return result(
        STATUS_NOT_ON_BRANCH,
        f"{short_pin} is not on {branch}; {short_suggestion} on {branch} has the same tree. "
        f"Repin: git -C {pin.path} fetch origin && git -C {pin.path} checkout {short_suggestion}"
        f" && git add {pin.path}",
        branch,
        suggested_commit,
    )


def check_submodule_pins(repository: Path) -> list[SubmodulePinCheck]:
    """
    check_submodule_pin for every pin, each in its own temporary directory.
    """
    results: list[SubmodulePinCheck] = []
    for pin in list_submodule_pins(repository):
        with tempfile.TemporaryDirectory(prefix="submodule-pin-") as work_directory:
            results.append(check_submodule_pin(pin, Path(work_directory)))
    return results


def fetch_without_blobs(
    bare_repository: Path, reference_specification: str
) -> subprocess.CompletedProcess[str]:
    return run_git(
        bare_repository,
        "fetch",
        "--quiet",
        "--no-tags",
        "--filter=blob:none",
        UPSTREAM_REMOTE_NAME,
        reference_specification,
    )


def last_line(text: str) -> str:
    lines = [line for line in text.strip().splitlines() if line.strip()]
    return lines[-1] if lines else "no output"


def run_git(directory: Path | None, *args: str) -> subprocess.CompletedProcess[str]:
    command = ["git", *(["-C", str(directory)] if directory else []), *args]
    return subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT_SECONDS,
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="devops-tools check-submodule-pins",
        description="Check that every submodule pin is a commit on its upstream branch.",
    )
    parser.add_argument(
        "--repository",
        type=Path,
        default=Path("."),
        help="Path to the git checkout",
    )
    parser.add_argument("--json", action="store_true", help="Print one JSON array of results")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(list(sys.argv[1:] if argv is None else argv))
    results = check_submodule_pins(args.repository.resolve())
    if args.json:
        print(json.dumps([dataclasses.asdict(result) for result in results], indent=2))
    else:
        if not results:
            print("No submodules.")
        for result in results:
            print(f"{result.status}: {result.message}")
    return 0 if all(result.status == STATUS_ON_BRANCH for result in results) else 1


if __name__ == "__main__":
    sys.exit(main())
