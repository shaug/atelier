#!/usr/bin/env bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
PUBLISH_SCRIPTS_DIR="${ROOT_DIR}/src/atelier/skills/publish/scripts"

create_temp_repo() {
  local repo
  repo="$(mktemp -d)"
  git -C "$repo" init -q
  git -C "$repo" config user.email "test@example.com"
  git -C "$repo" config user.name "Test User"
  echo "$repo"
}

create_commit() {
  local repo="$1"
  local filename="$2"
  echo "content" > "${repo}/${filename}"
  git -C "$repo" add "$filename"
  git -C "$repo" commit -m "add ${filename}" -q
}

teardown() {
  if [[ -n "${TMP_REPO:-}" && -d "${TMP_REPO}" ]]; then
    rm -rf "${TMP_REPO}"
  fi
  unset TMP_REPO
}

test_ensure_clean_tree_passes_on_clean_repo() {
  TMP_REPO="$(create_temp_repo)"
  "${PUBLISH_SCRIPTS_DIR}/ensure_clean_tree.sh" "$TMP_REPO" >/dev/null 2>&1
  assert_equals 0 "$?"
}

test_ensure_clean_tree_fails_on_dirty_repo() {
  TMP_REPO="$(create_temp_repo)"
  echo "dirty" > "${TMP_REPO}/dirty.txt"
  "${PUBLISH_SCRIPTS_DIR}/ensure_clean_tree.sh" "$TMP_REPO" >/dev/null 2>&1
  assert_equals 1 "$?"
}

test_ensure_clean_tree_fails_on_non_repo() {
  TMP_REPO="$(mktemp -d)"
  "${PUBLISH_SCRIPTS_DIR}/ensure_clean_tree.sh" "$TMP_REPO" >/dev/null 2>&1
  assert_equals 2 "$?"
}

test_run_required_checks_executes_commands() {
  TMP_REPO="$(create_temp_repo)"
  "${PUBLISH_SCRIPTS_DIR}/run_required_checks.sh" \
    "$TMP_REPO" \
    "echo ok > marker.txt" \
    "test -f marker.txt" \
    >/dev/null 2>&1
  assert_equals 0 "$?"
  assert_file_exists "${TMP_REPO}/marker.txt"
}

test_create_finalization_tag_creates_tag() {
  TMP_REPO="$(create_temp_repo)"
  create_commit "$TMP_REPO" "init.txt"
  "${PUBLISH_SCRIPTS_DIR}/create_finalization_tag.sh" "$TMP_REPO" "feat/demo" \
    >/dev/null 2>&1
  assert_equals 0 "$?"
  git -C "$TMP_REPO" rev-parse -q --verify "refs/tags/atelier/feat/demo/finalized" \
    >/dev/null 2>&1
  assert_equals 0 "$?"
}

test_create_finalization_tag_fails_when_tag_exists() {
  TMP_REPO="$(create_temp_repo)"
  create_commit "$TMP_REPO" "init.txt"
  "${PUBLISH_SCRIPTS_DIR}/create_finalization_tag.sh" "$TMP_REPO" "feat/demo" \
    >/dev/null 2>&1
  "${PUBLISH_SCRIPTS_DIR}/create_finalization_tag.sh" "$TMP_REPO" "feat/demo" \
    >/dev/null 2>&1
  assert_equals 1 "$?"
}
