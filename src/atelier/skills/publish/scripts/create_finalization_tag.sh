#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "Usage: create_finalization_tag.sh <repo_path> <branch_name>" >&2
  exit 2
fi

repo_path="$1"
branch_name="$2"

if [[ -z "$branch_name" ]]; then
  echo "Branch name is required" >&2
  exit 2
fi

if ! git -C "$repo_path" rev-parse --git-dir >/dev/null 2>&1; then
  echo "Not a git repository: $repo_path" >&2
  exit 2
fi

tag="atelier/${branch_name}/finalized"

if git -C "$repo_path" rev-parse -q --verify "refs/tags/$tag" >/dev/null; then
  echo "Tag already exists: $tag" >&2
  exit 1
fi

git -C "$repo_path" tag "$tag"
echo "Created tag: $tag"
