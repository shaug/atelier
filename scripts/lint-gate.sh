#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/.." && pwd)"

resolve_ruff_cmd() {
  if [[ -n "${ATELIER_RUFF_BIN:-}" ]]; then
    RUFF_CMD=("${ATELIER_RUFF_BIN}")
    return 0
  fi
  if command -v uv >/dev/null 2>&1; then
    RUFF_CMD=(uv run ruff)
    return 0
  fi
  if command -v ruff >/dev/null 2>&1; then
    RUFF_CMD=(ruff)
    return 0
  fi
  echo "lint-gate: missing Ruff runtime (uv or ruff not found)." >&2
  return 1
}

resolve_pyright_cmd() {
  if [[ -n "${ATELIER_PYRIGHT_BIN:-}" ]]; then
    PYRIGHT_CMD=("${ATELIER_PYRIGHT_BIN}")
    return 0
  fi
  if command -v uv >/dev/null 2>&1; then
    PYRIGHT_CMD=(uv run --extra dev pyright)
    return 0
  fi
  if command -v pyright >/dev/null 2>&1; then
    PYRIGHT_CMD=(pyright)
    return 0
  fi
  echo "lint-gate: missing pyright runtime (uv or pyright not found)." >&2
  return 1
}

resolve_shellcheck_cmd() {
  if command -v uv >/dev/null 2>&1; then
    SHELLCHECK_CMD=(uv run --extra dev shellcheck)
    return 0
  fi
  if command -v shellcheck >/dev/null 2>&1; then
    SHELLCHECK_CMD=(shellcheck)
    return 0
  fi
  echo "lint-gate: missing shellcheck runtime (uv or shellcheck not found)." >&2
  return 1
}

run_ruff_check() {
  (cd "${repo_root}" && "${RUFF_CMD[@]}" check --select I,RUF022 "$@")
}

run_ruff_format_check() {
  (cd "${repo_root}" && "${RUFF_CMD[@]}" format --check "$@")
}

run_pyright() {
  (cd "${repo_root}" && "${PYRIGHT_CMD[@]}")
}

run_shellcheck_publish_scripts() {
  (cd "${repo_root}" && "${SHELLCHECK_CMD[@]}" -x src/atelier/skills/publish/scripts/*.sh)
}

run_staged_python_gate() {
  local -a staged_python_files=("$@")
  if [[ ${#staged_python_files[@]} -eq 0 ]]; then
    exit 0
  fi

  resolve_ruff_cmd
  run_ruff_check "${staged_python_files[@]}"
  run_ruff_format_check "${staged_python_files[@]}"

  # Test fixtures without project metadata can skip pyright.
  if [[ -n "${ATELIER_PYRIGHT_BIN:-}" || -f "${repo_root}/pyproject.toml" ]]; then
    resolve_pyright_cmd
    run_pyright
  fi
}

run_full_gate() {
  resolve_ruff_cmd
  resolve_shellcheck_cmd
  resolve_pyright_cmd
  run_ruff_check .
  run_ruff_format_check .
  run_shellcheck_publish_scripts
  run_pyright
}

main() {
  case "${1:-}" in
    "")
      run_full_gate
      ;;
    --staged-python)
      shift
      run_staged_python_gate "$@"
      ;;
    *)
      echo "Usage: scripts/lint-gate.sh [--staged-python <file>...]" >&2
      exit 2
      ;;
  esac
}

main "$@"
