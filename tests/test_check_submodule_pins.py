"""
Submodule pins on upstream branches, checked against local upstream repositories.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from devops_tools import check_submodule_pins as PINS
from devops_tools import constants as CONSTANTS


def git(repository: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repository), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def init_repository(path: Path, default_branch: str = "main") -> Path:
    path.mkdir(parents=True)
    git(path, "init", "-q", "-b", default_branch)
    git(path, "config", "user.email", "test@example.com")
    git(path, "config", "user.name", "Test")
    # GitHub serves any commit reachable from a ref, including pull request heads.
    git(path, "config", "uploadpack.allowReachableSHA1InWant", "true")
    return path


def commit_file(repository: Path, relative: str, text: str, message: str) -> str:
    path = repository / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    git(repository, "add", "-A")
    git(repository, "commit", "-q", "-m", message)
    return git(repository, "rev-parse", "HEAD")


@pytest.fixture
def upstream(tmp_path: Path) -> dict[str, str | Path]:
    """
    An upstream library: main with two commits, a pull request branch whose head was then
    squash-merged into main with the same tree, an unmerged branch, and a develop branch.
    """
    repository = init_repository(tmp_path / "library")
    commit_file(repository, "README.md", "one\n", "First")
    base_commit = commit_file(repository, "README.md", "two\n", "Second")
    git(repository, "switch", "-q", "-c", "pull-request")
    pull_request_head = commit_file(repository, "feature.txt", "feature\n", "Feature")
    git(repository, "switch", "-q", "main")
    squash_merge_commit = commit_file(repository, "feature.txt", "feature\n", "Feature (#14)")
    git(repository, "switch", "-q", "-c", "unmerged", base_commit)
    unmerged_commit = commit_file(repository, "draft.txt", "draft\n", "Draft")
    git(repository, "switch", "-q", "-c", "develop", "main")
    develop_commit = commit_file(repository, "develop.txt", "develop\n", "Develop")
    git(repository, "switch", "-q", "main")
    return {
        "path": repository,
        "main_commit": squash_merge_commit,
        "pull_request_head": pull_request_head,
        "unmerged_commit": unmerged_commit,
        "develop_commit": develop_commit,
    }


def make_superproject(
    tmp_path: Path,
    pins: list[tuple[str, str, str, str | None]],
) -> Path:
    """
    A repository whose HEAD has a gitlink and a .gitmodules entry per (path, url, commit, branch).
    """
    repository = init_repository(tmp_path / "superproject")
    gitmodules_lines: list[str] = []
    for submodule_path, url, commit, branch in pins:
        git(repository, "update-index", "--add", "--cacheinfo", f"160000,{commit},{submodule_path}")
        gitmodules_lines += [
            f'[submodule "{submodule_path}"]',
            f"\tpath = {submodule_path}",
            f"\turl = {url}",
        ]
        if branch is not None:
            gitmodules_lines.append(f"\tbranch = {branch}")
    (repository / ".gitmodules").write_text("\n".join(gitmodules_lines) + "\n", encoding="utf-8")
    git(repository, "add", ".gitmodules")
    git(repository, "commit", "-q", "-m", "Pin")
    return repository


def check_one(tmp_path: Path, url: str, commit: str, branch: str | None):
    repository = make_superproject(tmp_path, [("libs/library", url, commit, branch)])
    results = PINS.check_submodule_pins(repository)
    assert len(results) == 1
    return results[0]


def test_pins_are_listed_from_head_with_url_and_branch(tmp_path: Path, upstream):
    commit = str(upstream["main_commit"])
    repository = make_superproject(
        tmp_path,
        [
            ("libs/zeta", str(upstream["path"]), commit, None),
            ("libs/alpha", str(upstream["path"]), commit, "develop"),
        ],
    )
    pins = PINS.list_submodule_pins(repository)
    assert [pin.path for pin in pins] == ["libs/alpha", "libs/zeta"]
    assert pins[0].branch == "develop"
    assert pins[1].branch is None
    assert pins[1].url == str(upstream["path"])
    assert pins[1].pinned_commit == commit


def test_repository_without_submodules_has_no_pins(tmp_path: Path):
    repository = init_repository(tmp_path / "plain")
    commit_file(repository, "README.md", "plain\n", "Initial")
    assert PINS.list_submodule_pins(repository) == []


def test_remote_default_branch_is_read_from_its_head(tmp_path: Path):
    repository = init_repository(tmp_path / "trunk-library", default_branch="trunk")
    commit_file(repository, "README.md", "trunk\n", "Initial")
    assert PINS.find_remote_default_branch(str(repository)) == "trunk"


def test_unreachable_remote_has_no_default_branch(tmp_path: Path):
    assert PINS.find_remote_default_branch(str(tmp_path / "missing")) is None


def test_pin_on_the_default_branch_passes(tmp_path: Path, upstream):
    result = check_one(tmp_path, str(upstream["path"]), str(upstream["main_commit"]), None)
    assert result.status == CONSTANTS.STATUS_ON_BRANCH
    assert result.branch == "main"
    assert result.suggested_commit is None


def test_older_commit_on_the_branch_passes(tmp_path: Path, upstream):
    first_commit = git(Path(upstream["path"]), "rev-list", "--max-parents=0", "main")
    result = check_one(tmp_path, str(upstream["path"]), first_commit, None)
    assert result.status == CONSTANTS.STATUS_ON_BRANCH


def test_squash_merged_pull_request_head_suggests_the_merge_commit(tmp_path: Path, upstream):
    result = check_one(tmp_path, str(upstream["path"]), str(upstream["pull_request_head"]), None)
    assert result.status == CONSTANTS.STATUS_NOT_ON_BRANCH
    assert result.suggested_commit == upstream["main_commit"]
    assert str(upstream["main_commit"])[:12] in result.message


def test_unmerged_commit_fails_without_a_suggestion(tmp_path: Path, upstream):
    result = check_one(tmp_path, str(upstream["path"]), str(upstream["unmerged_commit"]), None)
    assert result.status == CONSTANTS.STATUS_NOT_ON_BRANCH
    assert result.suggested_commit is None


def test_commit_the_remote_does_not_have_is_missing(tmp_path: Path, upstream):
    result = check_one(tmp_path, str(upstream["path"]), "1" * 40, None)
    assert result.status == CONSTANTS.STATUS_MISSING_ON_REMOTE


def test_branch_in_gitmodules_overrides_the_default_branch(tmp_path: Path, upstream):
    url = str(upstream["path"])
    develop_commit = str(upstream["develop_commit"])
    assert check_one(tmp_path / "with", url, develop_commit, "develop").status == (
        CONSTANTS.STATUS_ON_BRANCH
    )
    assert check_one(tmp_path / "without", url, develop_commit, None).status == (
        CONSTANTS.STATUS_NOT_ON_BRANCH
    )


def test_unreachable_upstream_is_a_fetch_failure(tmp_path: Path, upstream):
    result = check_one(tmp_path, str(tmp_path / "missing"), str(upstream["main_commit"]), None)
    assert result.status == CONSTANTS.STATUS_FETCH_FAILED


def test_check_leaves_the_submodule_checkout_alone(tmp_path: Path, upstream):
    repository = make_superproject(
        tmp_path, [("libs/library", str(upstream["path"]), str(upstream["main_commit"]), None)]
    )
    # A clone without --recurse-submodules leaves the submodule directory empty.
    submodule_directory = repository / "libs" / "library"
    submodule_directory.mkdir(parents=True)
    status_before = git(repository, "status", "--porcelain")
    PINS.check_submodule_pins(repository)
    assert list(submodule_directory.iterdir()) == []
    assert git(repository, "status", "--porcelain") == status_before


def test_main_exits_0_when_every_pin_is_on_its_branch(tmp_path: Path, upstream, capsys):
    repository = make_superproject(
        tmp_path, [("libs/library", str(upstream["path"]), str(upstream["main_commit"]), None)]
    )
    assert PINS.main(["--repository", str(repository)]) == 0
    assert "libs/library" in capsys.readouterr().out


def test_main_exits_1_and_prints_json_for_a_bad_pin(tmp_path: Path, upstream, capsys):
    repository = make_superproject(
        tmp_path,
        [("libs/library", str(upstream["path"]), str(upstream["pull_request_head"]), None)],
    )
    assert PINS.main(["--repository", str(repository), "--json"]) == 1
    results = json.loads(capsys.readouterr().out)
    assert results[0]["status"] == CONSTANTS.STATUS_NOT_ON_BRANCH
    assert results[0]["suggested_commit"] == upstream["main_commit"]
