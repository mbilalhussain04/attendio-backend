#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"

"$PYTHON_BIN" -m pip install \
  -r "$ROOT_DIR/requirements/common.txt" \
  -r "$ROOT_DIR/requirements/auth-extra.txt" \
  -r "$ROOT_DIR/requirements/attendance-extra.txt" \
  -r "$ROOT_DIR/requirements/storage-extra.txt" \
  -r "$ROOT_DIR/requirements/dev.txt"
