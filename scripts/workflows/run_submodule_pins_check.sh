#!/usr/bin/env bash
# Check that every submodule pointer of the current checkout is a commit on its upstream branch.
# Usage: DEVOPS_TOOLS_VERSION=<sha> run_submodule_pins_check.sh
set -euo pipefail
uvx --from "git+https://github.com/SETA1609/devops_tools@$DEVOPS_TOOLS_VERSION" \
    devops-tools check-submodule-pins
