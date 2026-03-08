#!/usr/bin/env bash
set -euo pipefail

SUPPORTED_PYTHON_VERSION="3.11"
DEFAULT_VENV_PATH=".venv"

usage() {
  echo "Usage: scripts/supported-python.sh <version|run|venv> [args...]" >&2
}

is_valid_venv() {
  local venv_path="$1"

  [[ -f "${venv_path}/pyvenv.cfg" ]] || return 1
  [[ -x "${venv_path}/bin/python" || -x "${venv_path}/bin/python3" ]] && return 0
  [[ -x "${venv_path}/Scripts/python.exe" ]]
}

remove_invalid_default_venv() {
  if [[ ! -e "${DEFAULT_VENV_PATH}" ]]; then
    return
  fi

  if is_valid_venv "${DEFAULT_VENV_PATH}"; then
    return
  fi

  rm -rf "${DEFAULT_VENV_PATH}"
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
      if [[ $# -eq 0 || ( $# -eq 1 && "$1" == --* ) ]]; then
        remove_invalid_default_venv
      fi
      exec uv venv --python "${SUPPORTED_PYTHON_VERSION}" --allow-existing "$@"
      ;;
    *)
      usage
      exit 2
      ;;
  esac
}

main "$@"
