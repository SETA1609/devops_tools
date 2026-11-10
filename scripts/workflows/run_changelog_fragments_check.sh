#!/usr/bin/env bash
# Check the changelog fragments of the current checkout, and that the pull request's branch has one.
# Usage: DEVOPS_TOOLS_VERSION=<sha> [SETTINGS_FILE=<path>] [PULL_REQUEST_BRANCH=<name>] \
#        run_changelog_fragments_check.sh
set -euo pipefail
settings_arguments=()
if [ -n "${SETTINGS_FILE:-}" ]; then settings_arguments=(--settings-file "$SETTINGS_FILE"); fi
branch_arguments=()
if [ -n "${PULL_REQUEST_BRANCH:-}" ]; then branch_arguments=(--branch "$PULL_REQUEST_BRANCH"); fi
uvx --from "git+https://github.com/SETA1609/devops_tools@$DEVOPS_TOOLS_VERSION" \
    devops-tools changelog-fragments "${settings_arguments[@]}" check "${branch_arguments[@]}"
