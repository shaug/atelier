#!/usr/bin/env bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

create_temp_repo() {
  local repo
  repo="$(mktemp -d)"
  git -C "$repo" init -q
  git -C "$repo" config user.email "test@example.com"
  git -C "$repo" config user.name "Test User"
  echo "seed" > "${repo}/seed.txt"
  git -C "$repo" add seed.txt
  git -C "$repo" commit -m "chore(repo): seed" -q

  cp "${ROOT_DIR}/commitlint.config.cjs" "${repo}/commitlint.config.cjs"
  mkdir -p "${repo}/.githooks"
  cp "${ROOT_DIR}/.githooks/worktree-bootstrap.sh" "${repo}/.githooks/worktree-bootstrap.sh"
  cp "${ROOT_DIR}/.githooks/commit-msg" "${repo}/.githooks/commit-msg"
  cp "${ROOT_DIR}/.githooks/post-checkout" "${repo}/.githooks/post-checkout"
  chmod +x "${repo}/.githooks/worktree-bootstrap.sh" \
    "${repo}/.githooks/commit-msg" \
    "${repo}/.githooks/post-checkout"
  git -C "$repo" add commitlint.config.cjs .githooks
  git -C "$repo" commit -m "chore(repo): add hooks" -q

  echo "$repo"
}

teardown() {
  if [[ -n "${TMP_WORKTREE:-}" && -d "${TMP_WORKTREE}" ]]; then
    rm -rf "${TMP_WORKTREE}"
  fi
  if [[ -n "${TMP_REPO:-}" && -d "${TMP_REPO}" ]]; then
    rm -rf "${TMP_REPO}"
  fi
  unset TMP_REPO
  unset TMP_WORKTREE
}

test_bootstrap_sets_hookspath_and_exec_bits() {
  TMP_REPO="$(create_temp_repo)"
  chmod -x "${TMP_REPO}/.githooks/commit-msg" "${TMP_REPO}/.githooks/post-checkout"
  git -C "${TMP_REPO}" config --unset-all core.hooksPath || true

  "${TMP_REPO}/.githooks/worktree-bootstrap.sh" >/dev/null 2>&1
  assert_equals 0 "$?"

  local hooks_path
  hooks_path="$(git -C "${TMP_REPO}" config --local --get core.hooksPath)"
  assert_equals ".githooks" "${hooks_path}"

  local commit_msg_executable post_checkout_executable
  commit_msg_executable=1
  post_checkout_executable=1
  if [[ -x "${TMP_REPO}/.githooks/commit-msg" ]]; then
    commit_msg_executable=0
  fi
  if [[ -x "${TMP_REPO}/.githooks/post-checkout" ]]; then
    post_checkout_executable=0
  fi
  assert_equals 0 "${commit_msg_executable}"
  assert_equals 0 "${post_checkout_executable}"
}

test_commit_msg_uses_override_linter_binary() {
  TMP_REPO="$(create_temp_repo)"

  local fake_linter args_file msg_file expected actual
  fake_linter="${TMP_REPO}/fake-commitlint.sh"
  args_file="${TMP_REPO}/args.txt"
  msg_file="${TMP_REPO}/COMMIT_MSG"

  cat > "${fake_linter}" <<'SCRIPT'
#!/usr/bin/env bash
set -euo pipefail
printf '%s' "$*" > "${ATELIER_TEST_ARGS_FILE}"
SCRIPT
  chmod +x "${fake_linter}"

  echo "feat(repo): run hook" > "${msg_file}"
  ATELIER_COMMITLINT_BIN="${fake_linter}" \
    ATELIER_TEST_ARGS_FILE="${args_file}" \
    "${TMP_REPO}/.githooks/commit-msg" "${msg_file}" >/dev/null 2>&1
  assert_equals 0 "$?"

  expected="--config ${TMP_REPO}/commitlint.config.cjs --edit ${msg_file}"
  actual="$(cat "${args_file}")"
  assert_equals "${expected}" "${actual}"
}

test_post_checkout_repairs_hookspath_from_worktree() {
  TMP_REPO="$(create_temp_repo)"
  "${TMP_REPO}/.githooks/worktree-bootstrap.sh" >/dev/null 2>&1

  TMP_WORKTREE="${TMP_REPO}-wt"
  git -C "${TMP_REPO}" worktree add -q -b test/worktree-bootstrap "${TMP_WORKTREE}" HEAD
  git -C "${TMP_REPO}" config --unset-all core.hooksPath

  "${TMP_WORKTREE}/.githooks/post-checkout" old new 1 >/dev/null 2>&1
  assert_equals 0 "$?"

  local hooks_path
  hooks_path="$(git -C "${TMP_REPO}" config --local --get core.hooksPath)"
  assert_equals ".githooks" "${hooks_path}"
}
