#!/bin/sh
# devops-tools base entrypoint: make sure the (throwaway) home exists, then run the command.
# The runner sets HOME, the working directory, and git's safe.directory for the checkout.
set -eu

export HOME="${HOME:-/tmp/container-home}"
mkdir -p "$HOME" 2>/dev/null || true

if [ "$#" -eq 0 ]; then
    set -- bash
fi

exec "$@"
