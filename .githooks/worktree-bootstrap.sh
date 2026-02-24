#!/usr/bin/env bash
set -euo pipefail

HOOKS_PATH=".githooks"

main() {
  local script_dir repo_root
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  repo_root="$(cd "${script_dir}/.." && pwd)"

  if ! git -C "${repo_root}" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "worktree-bootstrap: ${repo_root} is not a git work tree" >&2
    return 1
  fi

  local required_hooks=(
    "${HOOKS_PATH}/worktree-bootstrap.sh"
    "${HOOKS_PATH}/pre-commit"
    "${HOOKS_PATH}/pre-push"
    "${HOOKS_PATH}/commit-msg"
    "${HOOKS_PATH}/post-checkout"
  )
  local hook_path
  for hook_path in "${required_hooks[@]}"; do
    if [[ ! -f "${repo_root}/${hook_path}" ]]; then
      echo "worktree-bootstrap: missing required hook file ${hook_path}" >&2
      return 1
    fi
    chmod +x "${repo_root}/${hook_path}"
  done

  local git_common_dir
  git_common_dir="$(git -C "${repo_root}" rev-parse --path-format=absolute --git-common-dir)"

  local git_dir
  git_dir="$(git -C "${repo_root}" rev-parse --path-format=absolute --git-dir)"

  local context="primary-worktree"
  if [[ "${git_dir}" != "${git_common_dir}" ]]; then
    context="linked-worktree"
  fi

  local current
  current="$(git config --file "${git_common_dir}/config" --get core.hooksPath || true)"

  if [[ "${current}" != "${HOOKS_PATH}" ]]; then
    git config --file "${git_common_dir}/config" core.hooksPath "${HOOKS_PATH}"
    if [[ "${ATELIER_HOOK_BOOTSTRAP_QUIET:-0}" != "1" ]]; then
      printf 'worktree-bootstrap: set core.hooksPath=%s (%s)\n' "${HOOKS_PATH}" "${context}"
    fi
  elif [[ "${ATELIER_HOOK_BOOTSTRAP_QUIET:-0}" != "1" ]]; then
    printf 'worktree-bootstrap: core.hooksPath already %s (%s)\n' "${HOOKS_PATH}" "${context}"
  fi
}

main "$@"
