#!/usr/bin/env bash
# Move the issue of a merged pull request to done, regenerate the roadmap story table, and commit
# that to the base branch. Each attempt starts again from the latest base branch, so two runs that
# race only retry. Run it in a checkout that holds nothing but the calling repository.
# Usage: DEVOPS_TOOLS_VERSION=<sha> BASE_BRANCH=<name> HEAD_BRANCH=<name> \
#        PULL_REQUEST_NUMBER=<number> MERGED_AT=<UTC timestamp> [SETTINGS_FILE=<path>] \
#        [RETRY_DELAY_SECONDS=<seconds>] close_merged_issue.sh
set -euo pipefail
maximum_attempt_count=5
retry_delay_seconds="${RETRY_DELAY_SECONDS:-5}"
settings_arguments=()
if [ -n "${SETTINGS_FILE:-}" ]; then settings_arguments=(--settings-file "$SETTINGS_FILE"); fi
git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
for ((attempt = 1; attempt <= maximum_attempt_count; attempt++)); do
    git fetch origin "$BASE_BRANCH"
    git reset --hard FETCH_HEAD
    uvx --from "git+https://github.com/SETA1609/devops_tools@$DEVOPS_TOOLS_VERSION" \
        devops-tools close-merged-issue "${settings_arguments[@]}" \
        --branch "$HEAD_BRANCH" \
        --pull-request-number "$PULL_REQUEST_NUMBER" \
        --merge-date "${MERGED_AT%%T*}"
    git add --all
    if git diff --cached --quiet; then
        echo "nothing to commit"
        exit 0
    fi
    git commit -m "Close the issue of pull request #$PULL_REQUEST_NUMBER"
    if git push origin "HEAD:$BASE_BRANCH"; then
        exit 0
    fi
    echo "the push lost a race on attempt $attempt; starting again"
    sleep "$((attempt * retry_delay_seconds))"
done
echo "could not push after $maximum_attempt_count attempts" >&2
exit 1
