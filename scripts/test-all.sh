#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "Running shared tests..."
(
  cd "$ROOT_DIR"
  export PYTHONPATH="$ROOT_DIR/shared/python"
  python -m pytest shared/tests
)

echo "Running docs gateway tests..."
(
  cd "$ROOT_DIR/docs-gateway"
  export PYTHONPATH="$PWD:$ROOT_DIR/shared/python"
  python -m pytest tests
)

echo "Running auth service tests..."
(
  cd "$ROOT_DIR/auth-service"
  export PYTHONPATH="$PWD:$ROOT_DIR/shared/python"
  python -m pytest tests
)

echo "Running attendance service tests..."
(
  cd "$ROOT_DIR/attendance-service"
  export PYTHONPATH="$PWD:$ROOT_DIR/shared/python"
  python -m pytest tests
)

echo "Running leave service tests..."
(
  cd "$ROOT_DIR/leave-service"
  export PYTHONPATH="$PWD:$ROOT_DIR/shared/python"
  python -m pytest tests
)

echo "All tests passed."
