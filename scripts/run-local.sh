#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT_DIR/.env"
PYTHON_BIN="${PYTHON_BIN:-python3}"

if [[ ! -f "$ENV_FILE" ]]; then
  cp "$ROOT_DIR/.env.example" "$ENV_FILE"
  echo "Created $ENV_FILE from .env.example"
fi

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

if ! command_exists "$PYTHON_BIN"; then
  echo "$PYTHON_BIN not found. Set PYTHON_BIN to your virtualenv Python executable."
  exit 1
fi

eval "$("$PYTHON_BIN" "$ROOT_DIR/scripts/export-env.py" "$ENV_FILE")"
export PYTHONPATH="$ROOT_DIR/shared/python:${PYTHONPATH:-}"
# Existing local env files created before leave-service do not have these keys.
export LEAVE_DB_NAME="${LEAVE_DB_NAME:-attendio_leave}"
if [[ -z "${LEAVE_DATABASE_URL:-}" && -n "${ATTENDANCE_DATABASE_URL:-}" ]]; then
  export LEAVE_DATABASE_URL="${ATTENDANCE_DATABASE_URL%/*}/$LEAVE_DB_NAME"
fi
export BILLING_DB_NAME="${BILLING_DB_NAME:-attendio_billing}"
if [[ -z "${BILLING_DATABASE_URL:-}" && -n "${AUTH_DATABASE_URL:-}" ]]; then
  export BILLING_DATABASE_URL="${AUTH_DATABASE_URL%/*}/$BILLING_DB_NAME"
fi

minio_is_ready() {
  "$PYTHON_BIN" - <<'PY' >/dev/null 2>&1
import os, urllib.request
endpoint = os.environ.get("MINIO_ENDPOINT", "localhost:9000")
scheme = "https" if os.environ.get("MINIO_SECURE", "false").lower() == "true" else "http"
urllib.request.urlopen(f"{scheme}://{endpoint}/minio/health/live", timeout=2)
PY
}

start_local_minio() {
  if minio_is_ready; then
    return
  fi
  if command_exists minio; then
    mkdir -p "${MINIO_DATA_DIR:-$HOME/minio-data}"
    MINIO_ROOT_USER="${MINIO_ACCESS_KEY:-minioadmin}" MINIO_ROOT_PASSWORD="${MINIO_SECRET_KEY:-minioadmin}" \
      minio server "${MINIO_DATA_DIR:-$HOME/minio-data}" --console-address ":9001" >/tmp/attendio-minio.log 2>&1 &
    minio_pid=$!
    for _ in {1..20}; do minio_is_ready && return; sleep 1; done
  elif command_exists docker && docker info >/dev/null 2>&1; then
    docker compose --env-file "$ENV_FILE" -f "$ROOT_DIR/docker-compose.yml" up -d minio >/dev/null
    for _ in {1..30}; do minio_is_ready && return; sleep 1; done
  fi
}

start_local_minio
"$PYTHON_BIN" "$ROOT_DIR/scripts/ensure-local-infra.py"

cleanup() {
  if [[ -n "${auth_pid:-}" ]]; then
    kill "$auth_pid" 2>/dev/null || true
  fi
  if [[ -n "${attendance_pid:-}" ]]; then
    kill "$attendance_pid" 2>/dev/null || true
  fi
  if [[ -n "${storage_pid:-}" ]]; then
    kill "$storage_pid" 2>/dev/null || true
  fi
  if [[ -n "${notification_pid:-}" ]]; then
    kill "$notification_pid" 2>/dev/null || true
  fi
  if [[ -n "${leave_pid:-}" ]]; then
    kill "$leave_pid" 2>/dev/null || true
  fi
  if [[ -n "${billing_pid:-}" ]]; then
    kill "$billing_pid" 2>/dev/null || true
  fi
  if [[ -n "${docs_pid:-}" ]]; then
    kill "$docs_pid" 2>/dev/null || true
  fi
  if [[ -n "${minio_pid:-}" ]]; then
    kill "$minio_pid" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

(
  cd "$ROOT_DIR/auth-service"
  "$PYTHON_BIN" -m alembic upgrade head
  "$PYTHON_BIN" run.py
) &
auth_pid=$!

(
  cd "$ROOT_DIR/attendance-service"
  "$PYTHON_BIN" -m alembic upgrade head
  "$PYTHON_BIN" run.py
) &
attendance_pid=$!

(
  cd "$ROOT_DIR/storage-service"
  "$PYTHON_BIN" -m alembic upgrade head
  "$PYTHON_BIN" run.py
) &
storage_pid=$!

(
  cd "$ROOT_DIR/notification-service"
  "$PYTHON_BIN" -m alembic upgrade head
  "$PYTHON_BIN" run.py
) &
notification_pid=$!

(
  cd "$ROOT_DIR/leave-service"
  "$PYTHON_BIN" -m alembic upgrade head
  "$PYTHON_BIN" run.py
) &
leave_pid=$!

(
  cd "$ROOT_DIR/billing-service"
  "$PYTHON_BIN" run.py
) &
billing_pid=$!

(
  cd "$ROOT_DIR/docs-gateway"
  "$PYTHON_BIN" -m uvicorn main:app --host "${APP_HOST:-0.0.0.0}" --port "${DOCS_GATEWAY_PORT:-8090}" --reload
) &
docs_pid=$!

echo "Unified Swagger: http://localhost:${DOCS_GATEWAY_PORT:-8090}/docs"
echo "Unified OpenAPI JSON: http://localhost:${DOCS_GATEWAY_PORT:-8090}/openapi.json"
echo "Auth Swagger: http://localhost:${AUTH_APP_PORT:-8000}/docs"
echo "Auth OpenAPI JSON: http://localhost:${AUTH_APP_PORT:-8000}/openapi.json"
echo "Auth health: http://localhost:${AUTH_APP_PORT:-8000}/api/v1/health"
echo "Attendance Swagger: http://localhost:${ATTENDANCE_APP_PORT:-8001}/docs"
echo "Attendance OpenAPI JSON: http://localhost:${ATTENDANCE_APP_PORT:-8001}/openapi.json"
echo "Attendance health: http://localhost:${ATTENDANCE_APP_PORT:-8001}/health"
echo "Storage Swagger: http://localhost:${STORAGE_APP_PORT:-8002}/docs"
echo "Storage health: http://localhost:${STORAGE_APP_PORT:-8002}/api/v1/storage/health"
echo "Notification Swagger: http://localhost:${NOTIFICATION_APP_PORT:-8003}/docs"
echo "Notification health: http://localhost:${NOTIFICATION_APP_PORT:-8003}/api/v1/notifications/health"
echo "Leave Swagger: http://localhost:${LEAVE_APP_PORT:-8004}/docs"
echo "Leave health: http://localhost:${LEAVE_APP_PORT:-8004}/health"
echo "Billing Swagger: http://localhost:${BILLING_APP_PORT:-8005}/docs"
echo "Billing health: http://localhost:${BILLING_APP_PORT:-8005}/health"
wait "$auth_pid" "$attendance_pid" "$storage_pid" "$notification_pid" "$leave_pid" "$billing_pid" "$docs_pid"
