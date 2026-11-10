#!/usr/bin/env bash
# Rebase each open pull request of the current checkout's repository onto its main branch.
# Usage: DEVOPS_TOOLS_VERSION=<sha> GITHUB_TOKEN=<token> [SETTINGS_FILE=<path>] \
#        run_rebase_open_branches.sh
set -euo pipefail
settings_arguments=()
if [ -n "${SETTINGS_FILE:-}" ]; then settings_arguments=(--settings-file "$SETTINGS_FILE"); fi
uvx --from "git+https://github.com/SETA1609/devops_tools@$DEVOPS_TOOLS_VERSION" \
    devops-tools rebase-open-branches "${settings_arguments[@]}"
