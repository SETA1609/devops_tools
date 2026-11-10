#!/usr/bin/env bash
# Reject a devops-tools-version that is not a full 40-character commit SHA, before a reusable
# workflow installs that version.
# Usage: DEVOPS_TOOLS_VERSION=<sha> check_devops_tools_version.sh
set -euo pipefail
if ! [[ "$DEVOPS_TOOLS_VERSION" =~ ^[0-9a-f]{40}$ ]]; then
    echo "devops-tools-version must be a full 40-character commit SHA, got: $DEVOPS_TOOLS_VERSION" >&2
    exit 1
fi
