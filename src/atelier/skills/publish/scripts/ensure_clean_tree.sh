#!/usr/bin/env bash
set -euo pipefail

repo_path="${1:-.}"

if ! git -C "$repo_path" rev-parse --git-dir >/dev/null 2>&1; then
  echo "Not a git repository: $repo_path" >&2
  exit 2
fi

status="$(git -C "$repo_path" status --porcelain)"
if [[ -n "$status" ]]; then
  echo "Working tree is dirty: $repo_path" >&2
  echo "$status" >&2
  exit 1
fi

echo "Working tree clean: $repo_path"
