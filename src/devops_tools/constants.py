"""
Constants shared by the devops_tools modules.
"""

from __future__ import annotations

import re

# Run log
RUN_LOG_FILE_SUFFIX = ".log"
OLDER_THAN_DAYS_FLAG = "--older-than-days"
SECONDS_PER_DAY = 86_400
EXIT_CODE_PROGRAM_NOT_FOUND = 127
EXIT_CODE_SIGNAL_BASE = 128

# CLI exit codes
EXIT_CODE_SETUP_ERROR = 1
EXIT_CODE_USAGE_ERROR = 2

# CLI
DEFAULT_LOG_DIRECTORY = "cache/logs"
LOG_DIRECTORY_FLAG = "--log-directory"
LOG_NAME_PATTERN = r"[A-Za-z0-9][A-Za-z0-9._-]*"

# Repository settings: `[tool.devops-tools]` in pyproject.toml
SETTINGS_FILE_NAME = "pyproject.toml"
SETTINGS_TABLE_PATH = ("tool", "devops-tools")
DEFAULT_MAIN_BRANCH = "main"
# Letters and digits, an optional `.N`, then a dash and a number: AB-12, AB1.1-02, issue-3.
DEFAULT_ISSUE_ID_PATTERN = r"[A-Za-z][A-Za-z0-9]*(?:\.[0-9]+)?-[0-9]+"
DEFAULT_CHANGES_DIRECTORY = "changes"
DEFAULT_CHANGELOG_FILE = "CHANGELOG.md"

# Changelog fragments
CHANGES_README_FILE_NAME = "README.md"
PULL_REQUEST_NUMBER_IN_SUBJECT = re.compile(r"\(#(?P<number>[0-9]+)\)\s*$")
CHANGELOG_LAST_UPDATED_LINE = re.compile(r"^Last updated: \S+$", re.MULTILINE)
CHANGELOG_SECTION_HEADING = re.compile(r"^## ", re.MULTILINE)

# Submodule pins
GITLINK_MODE = "160000"
STATUS_ON_BRANCH = "on_branch"
STATUS_NOT_ON_BRANCH = "not_on_branch"
STATUS_MISSING_ON_REMOTE = "missing_on_remote"
STATUS_FETCH_FAILED = "fetch_failed"
UPSTREAM_REMOTE_NAME = "upstream"
UPSTREAM_BRANCH_REFERENCE = "refs/remotes/upstream/pinned-branch"
SHORT_COMMIT_LENGTH = 12
GIT_TIMEOUT_SECONDS = 300

# Rebase open branches
CHANGELOG_MERGE_DRIVER = "changelog-entries"
ATTRIBUTES_BEGIN = "# rebase-open-branches changelog-entries begin"
ATTRIBUTES_END = "# rebase-open-branches changelog-entries end"
GITHUB_API_TIMEOUT_SECONDS = 30
SAFE_BRANCH_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]*")
LAST_UPDATED_TIMESTAMP_LINE = re.compile(r"^Last updated: (\S+)$", re.MULTILINE)

# Container runner: `[tool.devops-tools.container]`
CONTAINER_SETTINGS_TABLE_NAME = "container"
DEFAULT_DOCKERFILE = "container/Dockerfile"
DEFAULT_CONTAINER_HOME_DIRECTORY = "/tmp/container-home"
CONTAINER_KEPT_CACHE_MOUNT = "/kept-cache"
DEFAULT_PROTECTED_DIRECTORIES = ("cache/logs",)
DEFAULT_IMAGE_TAG_WITHOUT_VERSION = "latest"
SUPPORTED_CONTAINER_BINARIES = ("docker", "podman")
KEEP_CACHE_FLAG = "--keep-cache"
IMAGE_OVERRIDE_ENVIRONMENT_VARIABLE = "IMAGE"
RUN_AS_ROOT_ENVIRONMENT_VARIABLE = "CONTAINER_AS_ROOT"
BUILT_IN_CONTAINER_ACTIONS = ("image", "exec", "shell", "prune", "clean", "agent")
CONTAINER_COMMAND_NAME_PATTERN = re.compile(r"[a-z][a-z0-9-]*")
CONTAINER_IMAGE_NAME_PATTERN = re.compile(r"[a-z0-9][a-z0-9._/-]*")

# Shared base image, shipped in the package
SHIPPED_IMAGES_DIRECTORY_NAME = "container_images"
BASE_IMAGE_DOCKERFILE_NAME = "base.Dockerfile"
BASE_IMAGE_REPOSITORY = "devops-tools-base"
BASE_IMAGE_BUILD_ARGUMENT = "BASE_IMAGE"
DOCKERFILE_BASE_IMAGE_ARGUMENT_LINE = re.compile(r"^ARG\s+BASE_IMAGE\s*$", re.MULTILINE)
DOCKERFILE_FROM_BASE_IMAGE_LINE = re.compile(r"^FROM\s+\$\{BASE_IMAGE\}(\s|$)", re.MULTILINE)
CONTENT_HASH_LENGTH = 12
