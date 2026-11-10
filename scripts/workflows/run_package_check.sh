#!/usr/bin/env bash
# Run one check of this package's continuous integration, from the repository root.
# Usage: run_package_check.sh tests|lint|format
set -euo pipefail
case "${1:-}" in
    tests) uv run pytest ;;
    lint) uv run ruff check ;;
    format) uv run ruff format --check ;;
    *)
        echo "usage: $0 tests|lint|format" >&2
        exit 2
        ;;
esac
