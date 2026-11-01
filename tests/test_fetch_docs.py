"""
Offline fetch-docs tests: every download goes through a fake.
"""

import json
import pathlib

import pytest

from devops_tools import fetch_docs
from devops_tools.exceptions import FetchDocsError

COMMIT_SHA = "70304594e73a0123456789abcdef0123456789ab"
VULKAN_SPEC_MAIN_COMMIT_URL = "https://api.github.com/repos/KhronosGroup/Vulkan-Docs/commits/main"
VULKAN_SPEC_HEAD_COMMIT_URL = "https://api.github.com/repos/KhronosGroup/Vulkan-Docs/commits/HEAD"


class FakeDownloader:
    """Serves fixed bytes per URL and records every URL asked for."""

    def __init__(self, bytes_by_url: dict[str, bytes]) -> None:
        self.bytes_by_url = bytes_by_url
        self.requested_urls: list[str] = []

    def __call__(self, url: str) -> bytes:
        self.requested_urls.append(url)
        if url not in self.bytes_by_url:
            raise FetchDocsError("download_failed", f"not found: {url}")
        return self.bytes_by_url[url]


def github_commit_response(commit_sha: str = COMMIT_SHA) -> bytes:
    return json.dumps({"sha": commit_sha}).encode()


def test_default_cache_directory_is_docs_cache_directory_under_the_repository(tmp_path):
    """
    What: find_default_cache_directory_path.
    When: the repository has no settings file.
    Then: the cache is cache/docs under the repository.
    """
    assert (
        fetch_docs.find_default_cache_directory_path(tmp_path, None) == tmp_path / "cache" / "docs"
    )


def test_default_cache_directory_follows_the_settings(tmp_path):
    """
    What: find_default_cache_directory_path.
    When: the settings set docs-cache-directory.
    Then: the cache is that directory under the repository.
    """
    (tmp_path / "pyproject.toml").write_text(
        '[tool.devops-tools]\ndocs-cache-directory = "build/docs-cache"\n'
    )
    expected = tmp_path / "build" / "docs-cache"
    assert fetch_docs.find_default_cache_directory_path(tmp_path, None) == expected


def test_command_without_a_cache_directory_saves_under_the_repository(tmp_path, capsys):
    """
    What: the fetch-docs url command.
    When: no --cache-directory is given.
    Then: the file is saved under the repository's docs cache, mirroring host and path.
    """
    url = "https://docs.example.org/page"
    exit_code = fetch_docs.main(
        ["url", url, "--repository", str(tmp_path)], FakeDownloader({url: b"page"})
    )
    assert exit_code == 0
    printed_summary = json.loads(capsys.readouterr().out)
    expected = tmp_path / "cache" / "docs" / "url" / "docs.example.org" / "page"
    assert pathlib.Path(printed_summary["cache_file_path"]) == expected


def test_command_with_bad_settings_prints_an_invalid_settings_error(tmp_path, capsys):
    """
    What: the fetch-docs command.
    When: the settings table has an unknown key.
    Then: it exits 1 with the error code invalid_settings.
    """
    (tmp_path / "pyproject.toml").write_text("[tool.devops-tools]\ntypo = 'x'\n")
    exit_code = fetch_docs.main(["list", "--repository", str(tmp_path)], FakeDownloader({}))
    assert exit_code == 1
    assert json.loads(capsys.readouterr().err)["error"]["code"] == "invalid_settings"


def test_safe_relative_path_keeps_a_normal_relative_path():
    """
    What: build_safe_relative_path.
    When: the path is a plain relative path.
    Then: it is kept as it is.
    """
    safe_path = fetch_docs.build_safe_relative_path("chapters/vertexpostproc.adoc")
    assert str(safe_path) == "chapters/vertexpostproc.adoc"


@pytest.mark.parametrize("untrusted_path", ["../escape.txt", "chapters/../../x", "/etc/passwd", ""])
def test_safe_relative_path_rejects_escapes_and_empty_paths(untrusted_path):
    """
    What: build_safe_relative_path.
    When: the path has `..`, starts at the root, or is empty.
    Then: it fails with invalid_path.
    """
    with pytest.raises(FetchDocsError) as error:
        fetch_docs.build_safe_relative_path(untrusted_path)
    assert error.value.error_code == "invalid_path"


def test_url_cache_file_path_mirrors_host_and_path(tmp_path):
    """
    What: build_url_cache_file_path.
    When: a URL has a host and a path.
    Then: the cache file is url/<host>/<path>.
    """
    cache_file_path = fetch_docs.build_url_cache_file_path(
        tmp_path, "https://wiki.example.org/Guide/Create_Window"
    )
    assert cache_file_path == tmp_path / "url" / "wiki.example.org" / "Guide" / "Create_Window"


def test_url_cache_file_path_saves_a_directory_url_as_index_html(tmp_path):
    """
    What: build_url_cache_file_path.
    When: the URL path ends in a slash.
    Then: the file is saved as index.html in that directory.
    """
    cache_file_path = fetch_docs.build_url_cache_file_path(
        tmp_path, "https://docs.example.org/learn/"
    )
    assert cache_file_path == tmp_path / "url" / "docs.example.org" / "learn" / "index.html"


def test_download_refuses_plain_http_before_any_network_access():
    """
    What: download_url_bytes.
    When: the URL is plain http.
    Then: it fails with https_required before any request.
    """
    with pytest.raises(FetchDocsError) as error:
        fetch_docs.download_url_bytes("http://example.com/page")
    assert error.value.error_code == "https_required"


def test_github_raw_file_url_points_at_the_exact_commit():
    """
    What: build_github_raw_file_url.
    When: a repository, a commit, and a file path are given.
    Then: the raw URL names that exact commit.
    """
    raw_url = fetch_docs.build_github_raw_file_url(
        "KhronosGroup/Vulkan-Docs", COMMIT_SHA, "chapters/fragops.adoc"
    )
    assert raw_url == (
        f"https://raw.githubusercontent.com/KhronosGroup/Vulkan-Docs/{COMMIT_SHA}/chapters/fragops.adoc"
    )


def test_resolving_a_reference_asks_the_github_commits_api():
    """
    What: resolve_github_reference_to_commit_sha.
    When: the commits API answers with a SHA for the reference.
    Then: that SHA is returned.
    """
    downloader = FakeDownloader({VULKAN_SPEC_MAIN_COMMIT_URL: github_commit_response()})
    commit_sha = fetch_docs.resolve_github_reference_to_commit_sha(
        "KhronosGroup/Vulkan-Docs", "main", downloader
    )
    assert commit_sha == COMMIT_SHA


@pytest.mark.parametrize("owner_and_repository", ["no-slash", "too/many/slashes", "../x", "a/"])
def test_resolving_rejects_a_malformed_repository_name(owner_and_repository):
    """
    What: resolve_github_reference_to_commit_sha.
    When: the repository name is not OWNER/REPOSITORY.
    Then: it fails with invalid_repository before any request.
    """
    with pytest.raises(FetchDocsError) as error:
        fetch_docs.resolve_github_reference_to_commit_sha(
            owner_and_repository, "main", FakeDownloader({})
        )
    assert error.value.error_code == "invalid_repository"


def test_resolving_rejects_a_response_without_a_commit_sha():
    """
    What: resolve_github_reference_to_commit_sha.
    When: the API reply has no commit SHA.
    Then: it fails with invalid_github_response.
    """
    downloader = FakeDownloader(
        {"https://api.github.com/repos/owner/repository/commits/main": b"{}"}
    )
    with pytest.raises(FetchDocsError) as error:
        fetch_docs.resolve_github_reference_to_commit_sha("owner/repository", "main", downloader)
    assert error.value.error_code == "invalid_github_response"


def test_vulkan_spec_chapter_names_become_chapter_file_paths():
    """
    What: build_vulkan_spec_chapter_file_paths.
    When: chapter names are given with and without .adoc.
    Then: each becomes chapters/<name>.adoc.
    """
    file_paths = fetch_docs.build_vulkan_spec_chapter_file_paths(["vertexpostproc", "fragops.adoc"])
    assert file_paths == ["chapters/vertexpostproc.adoc", "chapters/fragops.adoc"]


def test_vulkan_spec_chapter_names_cannot_escape_the_chapters_directory():
    """
    What: build_vulkan_spec_chapter_file_paths.
    When: a chapter name contains `..`.
    Then: it fails with invalid_path.
    """
    with pytest.raises(FetchDocsError) as error:
        fetch_docs.build_vulkan_spec_chapter_file_paths(["../README"])
    assert error.value.error_code == "invalid_path"


def test_fetching_a_url_saves_the_bytes_and_a_source_file(tmp_path):
    """
    What: fetch_url_document.
    When: an https URL is downloaded.
    Then: the bytes are saved and a .source.json next to them records the URL and the time.
    """
    url = "https://wiki.example.org/Guide/Create_Window"
    downloader = FakeDownloader({url: b"page text"})
    document = fetch_docs.fetch_url_document(url, tmp_path, downloader)
    assert document.source_url == url
    assert document.byte_count == len(b"page text")
    assert document.cache_file_path.read_bytes() == b"page text"
    source_file_path = document.cache_file_path.with_name(
        document.cache_file_path.name + ".source.json"
    )
    source_metadata = json.loads(source_file_path.read_text())
    assert source_metadata["url"] == url
    assert "fetched_at_utc" in source_metadata


def test_fetching_a_plain_http_url_is_refused(tmp_path):
    """
    What: fetch_url_document.
    When: the URL is plain http.
    Then: it fails with https_required.
    """
    with pytest.raises(FetchDocsError) as error:
        fetch_docs.fetch_url_document("http://example.com/", tmp_path, FakeDownloader({}))
    assert error.value.error_code == "https_required"


def test_fetching_github_files_saves_them_under_the_commit_with_source_metadata(tmp_path):
    """
    What: fetch_github_documents.
    When: a file is fetched from a repository at a tag.
    Then: it is saved under the resolved commit, and SOURCE.json records the repository, the
    reference, the commit, and the file.
    """
    raw_url = f"https://raw.githubusercontent.com/owner/repository/{COMMIT_SHA}/docs/guide.md"
    downloader = FakeDownloader(
        {
            "https://api.github.com/repos/owner/repository/commits/v1.0": github_commit_response(),
            raw_url: b"# Guide",
        }
    )
    summary = fetch_docs.fetch_github_documents(
        "owner/repository", ["docs/guide.md"], "v1.0", tmp_path, downloader
    )
    commit_directory_path = tmp_path / "github" / "owner" / "repository" / COMMIT_SHA[:12]
    assert (commit_directory_path / "docs" / "guide.md").read_bytes() == b"# Guide"
    source_metadata = json.loads((commit_directory_path / "SOURCE.json").read_text())
    assert source_metadata["repository"] == "owner/repository"
    assert source_metadata["reference"] == "v1.0"
    assert source_metadata["commit"] == COMMIT_SHA
    assert source_metadata["files"][0]["path"] == "docs/guide.md"
    assert source_metadata["files"][0]["url"] == raw_url
    assert summary["commit"] == COMMIT_SHA
    assert summary["files"][0]["cache_file_path"] == str(
        commit_directory_path / "docs" / "guide.md"
    )


def test_listing_the_cache_returns_every_source_file_sorted_by_path(tmp_path):
    """
    What: list_cached_documents.
    When: the cache holds a URL download and a GitHub download.
    Then: both are listed, sorted by source file path.
    """
    url = "https://wiki.example.org/Guide/Create_Window"
    raw_url = f"https://raw.githubusercontent.com/owner/repository/{COMMIT_SHA}/a.md"
    downloader = FakeDownloader(
        {
            url: b"page",
            "https://api.github.com/repos/owner/repository/commits/main": github_commit_response(),
            raw_url: b"a",
        }
    )
    fetch_docs.fetch_url_document(url, tmp_path, downloader)
    fetch_docs.fetch_github_documents("owner/repository", ["a.md"], "main", tmp_path, downloader)
    cached_documents = fetch_docs.list_cached_documents(tmp_path)
    assert [entry.get("commit") for entry in cached_documents] == [COMMIT_SHA, None]
    assert cached_documents[1]["url"] == url
    assert [entry["source_file_path"] for entry in cached_documents] == sorted(
        entry["source_file_path"] for entry in cached_documents
    )


def test_listing_an_empty_cache_returns_nothing(tmp_path):
    """
    What: list_cached_documents.
    When: the cache directory does not exist.
    Then: it returns an empty list.
    """
    assert fetch_docs.list_cached_documents(tmp_path / "missing") == []


def test_command_vulkan_spec_fetches_chapters_and_prints_json(tmp_path, capsys):
    """
    What: the fetch-docs vulkan-spec command.
    When: a chapter is fetched at the default reference.
    Then: it exits 0, prints the repository and commit, and downloads the chapter at that commit.
    """
    raw_url = (
        f"https://raw.githubusercontent.com/KhronosGroup/Vulkan-Docs/{COMMIT_SHA}"
        "/chapters/vertexpostproc.adoc"
    )
    downloader = FakeDownloader(
        {
            VULKAN_SPEC_HEAD_COMMIT_URL: github_commit_response(),
            raw_url: b"== Coordinate Transformations",
        }
    )
    exit_code = fetch_docs.main(
        ["vulkan-spec", "vertexpostproc", "--cache-directory", str(tmp_path)], downloader
    )
    assert exit_code == 0
    printed_summary = json.loads(capsys.readouterr().out)
    assert printed_summary["repository"] == "KhronosGroup/Vulkan-Docs"
    assert printed_summary["commit"] == COMMIT_SHA
    assert raw_url in downloader.requested_urls


def test_command_github_without_a_reference_uses_the_default_branch(tmp_path, capsys):
    """
    What: the fetch-docs github command.
    When: no --reference is given.
    Then: HEAD is resolved, so the repository's default branch is used whatever it is called.
    """
    raw_url = f"https://raw.githubusercontent.com/owner/repository/{COMMIT_SHA}/src/header.h"
    downloader = FakeDownloader(
        {
            # A repository whose default branch is master: only HEAD resolves without asking.
            "https://api.github.com/repos/owner/repository/commits/HEAD": github_commit_response(),
            raw_url: b"// header",
        }
    )
    exit_code = fetch_docs.main(
        ["github", "owner/repository", "src/header.h", "--cache-directory", str(tmp_path)],
        downloader,
    )
    assert exit_code == 0
    printed_summary = json.loads(capsys.readouterr().out)
    assert printed_summary["reference"] == "HEAD"
    assert printed_summary["commit"] == COMMIT_SHA


def test_command_url_prints_the_saved_file(tmp_path, capsys):
    """
    What: the fetch-docs url command.
    When: a URL is fetched into a given cache directory.
    Then: it prints the URL and the path of the saved file.
    """
    url = "https://docs.example.org/learn/"
    exit_code = fetch_docs.main(
        ["url", url, "--cache-directory", str(tmp_path)], FakeDownloader({url: b"<html>"})
    )
    assert exit_code == 0
    printed_summary = json.loads(capsys.readouterr().out)
    assert printed_summary["url"] == url
    assert pathlib.Path(printed_summary["cache_file_path"]).read_bytes() == b"<html>"


def test_command_list_prints_the_cached_documents(tmp_path, capsys):
    """
    What: the fetch-docs list command.
    When: the cache holds one URL download.
    Then: it prints that document.
    """
    url = "https://docs.example.org/learn/"
    fetch_docs.fetch_url_document(url, tmp_path, FakeDownloader({url: b"<html>"}))
    exit_code = fetch_docs.main(["list", "--cache-directory", str(tmp_path)], FakeDownloader({}))
    assert exit_code == 0
    printed_summary = json.loads(capsys.readouterr().out)
    assert printed_summary["documents"][0]["url"] == url


def test_command_errors_print_json_with_a_code_and_exit_1(tmp_path, capsys):
    """
    What: the fetch-docs command.
    When: the repository name is malformed.
    Then: nothing goes to stdout, stderr gets a JSON error with its code, and it exits 1.
    """
    exit_code = fetch_docs.main(
        ["github", "no-slash", "README.md", "--cache-directory", str(tmp_path)], FakeDownloader({})
    )
    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err)["error"]["code"] == "invalid_repository"
