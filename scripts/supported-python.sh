#!/usr/bin/env bash
set -euo pipefail

SUPPORTED_PYTHON_VERSION="3.11"

usage() {
  echo "Usage: scripts/supported-python.sh <version|run|venv> [args...]" >&2
}

main() {
  unset VIRTUAL_ENV

  if [[ $# -lt 1 ]]; then
    usage
    exit 2
  fi

  case "$1" in
    version)
      printf '%s\n' "${SUPPORTED_PYTHON_VERSION}"
      ;;
    run)
      shift
      exec uv run --python "${SUPPORTED_PYTHON_VERSION}" "$@"
      ;;
    venv)
      shift
      exec uv venv --python "${SUPPORTED_PYTHON_VERSION}" "$@"
      ;;
    *)
      usage
      exit 2
      ;;
  esac
}

main "$@"
