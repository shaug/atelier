#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
BASHUNIT="${SCRIPT_DIR}/vendor/bashunit"

cd "${ROOT_DIR}"
"${BASHUNIT}" test "tests/shell/publish_scripts_test.sh"
"${BASHUNIT}" test "tests/shell/repo_hooks_test.sh"
