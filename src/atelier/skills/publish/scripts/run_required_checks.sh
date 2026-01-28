#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "Usage: run_required_checks.sh <repo_path> <command> [<command> ...]" >&2
  exit 2
fi

repo_path="$1"
shift

if ! git -C "$repo_path" rev-parse --git-dir >/dev/null 2>&1; then
  echo "Not a git repository: $repo_path" >&2
  exit 2
fi

for cmd in "$@"; do
  echo "Running: $cmd"
  (cd "$repo_path" && bash -lc "$cmd")
done
