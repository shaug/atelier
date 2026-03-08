#!/usr/bin/env bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
SUPPORTED_PYTHON="${ROOT_DIR}/scripts/supported-python.sh"

setup_fake_uv() {
  local bin_dir="$1"
  local fake_uv="${bin_dir}/uv"

  cat > "${fake_uv}" <<'SCRIPT'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "${ATELIER_TEST_ARGS_FILE}"
SCRIPT
  chmod +x "${fake_uv}"
}

teardown() {
  if [[ -n "${TMP_DIR:-}" && -d "${TMP_DIR}" ]]; then
    rm -rf "${TMP_DIR}"
  fi
  unset TMP_DIR
}

test_supported_python_reports_current_policy_version() {
  local actual
  actual="$(bash "${SUPPORTED_PYTHON}" version)"
  assert_equals "3.11" "${actual}"
}

test_supported_python_run_pins_uv_to_python_311() {
  TMP_DIR="$(mktemp -d)"

  local args_file actual
  args_file="${TMP_DIR}/uv-args.txt"
  setup_fake_uv "${TMP_DIR}"

  PATH="${TMP_DIR}:${PATH}" \
    ATELIER_TEST_ARGS_FILE="${args_file}" \
    bash "${SUPPORTED_PYTHON}" run pytest >/dev/null 2>&1
  assert_equals 0 "$?"

  actual="$(cat "${args_file}")"
  assert_equals "run --python 3.11 pytest" "${actual}"
}

test_supported_python_venv_pins_uv_to_python_311() {
  TMP_DIR="$(mktemp -d)"

  local args_file actual
  args_file="${TMP_DIR}/uv-args.txt"
  setup_fake_uv "${TMP_DIR}"

  PATH="${TMP_DIR}:${PATH}" \
    ATELIER_TEST_ARGS_FILE="${args_file}" \
    bash "${SUPPORTED_PYTHON}" venv --clear >/dev/null 2>&1
  assert_equals 0 "$?"

  actual="$(cat "${args_file}")"
  assert_equals "venv --python 3.11 --allow-existing --clear" "${actual}"
}

test_supported_python_venv_recreates_invalid_default_environment() {
  TMP_DIR="$(mktemp -d)"

  local args_file actual
  args_file="${TMP_DIR}/uv-args.txt"
  mkdir -p "${TMP_DIR}/.venv/bin"
  printf '%s\n' '#!/usr/bin/env bash' > "${TMP_DIR}/.venv/bin/atelier"
  setup_fake_uv "${TMP_DIR}"

  (
    cd "${TMP_DIR}"
    PATH="${TMP_DIR}:${PATH}" \
      ATELIER_TEST_ARGS_FILE="${args_file}" \
      bash "${SUPPORTED_PYTHON}" venv >/dev/null 2>&1
  )
  assert_equals 0 "$?"

  assert_directory_not_exists "${TMP_DIR}/.venv"

  actual="$(cat "${args_file}")"
  assert_equals "venv --python 3.11 --allow-existing" "${actual}"
}

test_lint_gate_pins_uv_tooling_to_python_311() {
  TMP_DIR="$(mktemp -d)"

  local args_file first second third fourth shellcheck_uses_policy
  args_file="${TMP_DIR}/uv-args.txt"
  setup_fake_uv "${TMP_DIR}"

  PATH="${TMP_DIR}:${PATH}" \
    ATELIER_TEST_ARGS_FILE="${args_file}" \
    bash "${ROOT_DIR}/scripts/lint-gate.sh" >/dev/null 2>&1
  assert_equals 0 "$?"

  first="$(sed -n '1p' "${args_file}")"
  second="$(sed -n '2p' "${args_file}")"
  third="$(sed -n '3p' "${args_file}")"
  fourth="$(sed -n '4p' "${args_file}")"

  assert_equals "run --python 3.11 ruff check --select I,RUF022 ." "${first}"
  assert_equals "run --python 3.11 ruff format --check ." "${second}"

  shellcheck_uses_policy=1
  if [[ "${third}" == run\ --python\ 3.11\ --extra\ dev\ shellcheck\ -x\ * ]]; then
    shellcheck_uses_policy=0
  fi
  assert_equals 0 "${shellcheck_uses_policy}"

  assert_equals "run --python 3.11 --extra dev pyright" "${fourth}"
}
