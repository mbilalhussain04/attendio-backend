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

normalize_local_runtime_env() {
  if [[ "${APP_ENV:-development}" == "production" ]]; then
    return
  fi

  if [[ "${POSTGRES_HOST:-}" == "platform-postgres" ]]; then
    export POSTGRES_HOST=localhost
  fi

  local database_url_name database_url_value
  local postgres_port="${POSTGRES_PORT:-5432}"
  for database_url_name in \
    AUTH_DATABASE_URL \
    ATTENDANCE_DATABASE_URL \
    STORAGE_DATABASE_URL \
    NOTIFICATION_DATABASE_URL \
    LEAVE_DATABASE_URL \
    BILLING_DATABASE_URL; do
    database_url_value="${!database_url_name:-}"
    if [[ -n "$database_url_value" ]]; then
      database_url_value="${database_url_value//@platform-postgres:/@localhost:}"
      database_url_value="${database_url_value//@localhost:5432/@localhost:$postgres_port}"
      export "$database_url_name=$database_url_value"
    fi
  done

  export REDIS_URL="${REDIS_URL:-redis://localhost:6379/0}"
  export REDIS_URL="${REDIS_URL//\/\/redis:/\/\/localhost:}"
  export RABBITMQ_URL="${RABBITMQ_URL:-amqp://guest:guest@localhost:5672/}"
  export RABBITMQ_URL="${RABBITMQ_URL//@rabbitmq:/@localhost:}"
  export MINIO_ENDPOINT="${MINIO_ENDPOINT:-localhost:9000}"
  export MINIO_ENDPOINT="${MINIO_ENDPOINT//minio:/localhost:}"

  export AUTH_SERVICE_URL="${AUTH_SERVICE_URL:-http://localhost:8000}"
  export AUTH_SERVICE_URL="${AUTH_SERVICE_URL//auth-service/localhost}"
  export ATTENDANCE_SERVICE_URL="${ATTENDANCE_SERVICE_URL:-http://localhost:8001}"
  export ATTENDANCE_SERVICE_URL="${ATTENDANCE_SERVICE_URL//attendance-service/localhost}"
  export STORAGE_SERVICE_URL="${STORAGE_SERVICE_URL:-http://localhost:8002}"
  export STORAGE_SERVICE_URL="${STORAGE_SERVICE_URL//storage-service/localhost}"
  export NOTIFICATION_SERVICE_URL="${NOTIFICATION_SERVICE_URL:-http://localhost:8003}"
  export NOTIFICATION_SERVICE_URL="${NOTIFICATION_SERVICE_URL//notification-service/localhost}"
  export LEAVE_SERVICE_URL="${LEAVE_SERVICE_URL:-http://localhost:8004}"
  export LEAVE_SERVICE_URL="${LEAVE_SERVICE_URL//leave-service/localhost}"
  export BILLING_SERVICE_URL="${BILLING_SERVICE_URL:-http://localhost:8005}"
  export BILLING_SERVICE_URL="${BILLING_SERVICE_URL//billing-service/localhost}"
  export DOCS_GATEWAY_URL="${DOCS_GATEWAY_URL:-http://localhost:8090}"
  export DOCS_GATEWAY_URL="${DOCS_GATEWAY_URL//docs-gateway/localhost}"
}

normalize_local_runtime_env

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

postgres_is_ready() {
  "$PYTHON_BIN" - <<'PY' >/dev/null 2>&1
import os
from urllib.parse import quote

import psycopg

user = os.environ.get("POSTGRES_USER", "postgres")
password = os.environ.get("POSTGRES_PASSWORD", "")
host = os.environ.get("POSTGRES_HOST", "localhost")
port = os.environ.get("POSTGRES_PORT", "5432")
auth = quote(user)
if password:
    auth = f"{auth}:{quote(password)}"
with psycopg.connect(f"postgresql://{auth}@{host}:{port}/postgres", connect_timeout=2):
    pass
PY
}

start_local_postgres() {
  if postgres_is_ready; then
    return
  fi

  if ! command_exists initdb || ! command_exists pg_ctl || ! command_exists postgres; then
    return
  fi

  local data_dir="${ATTENDIO_LOCAL_POSTGRES_DIR:-$ROOT_DIR/.local-postgres}"
  local postgres_port="${POSTGRES_PORT:-55432}"
  mkdir -p "$data_dir"

  if [[ ! -s "$data_dir/PG_VERSION" ]]; then
    echo "Initializing local PostgreSQL in $data_dir..."
    initdb -D "$data_dir" -U "${POSTGRES_USER:-postgres}" --auth=trust >/dev/null
  fi

  echo "Starting local PostgreSQL on localhost:$postgres_port..."
  pg_ctl -D "$data_dir" \
    -o "-h 127.0.0.1 -p $postgres_port" \
    -l "$data_dir/postgres.log" \
    start >/dev/null

  for _ in {1..30}; do
    postgres_is_ready && return
    sleep 1
  done
}

start_local_redis() {
  if "$PYTHON_BIN" - <<'PY' >/dev/null 2>&1
import os
from urllib.parse import urlparse
import redis

url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
redis.Redis.from_url(url).ping()
PY
  then
    return
  fi

  if command_exists redis-server; then
    local redis_dir="${ATTENDIO_LOCAL_REDIS_DIR:-$ROOT_DIR/.local-redis}"
    mkdir -p "$redis_dir"
    echo "Starting local Redis on localhost:6379..."
    redis-server --port 6379 --dir "$redis_dir" --daemonize yes >/dev/null
  fi
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
  fi
}

start_local_postgres
start_local_redis
start_local_minio
"$PYTHON_BIN" "$ROOT_DIR/scripts/ensure-local-infra.py"

run_service_migration() {
  local service_dir="$1"
  local service_name="$2"
  echo "Running $service_name migrations..."
  (
    cd "$ROOT_DIR/$service_dir"
    "$PYTHON_BIN" -m alembic upgrade head
  )
}

run_service_migration "auth-service" "auth-service"
run_service_migration "attendance-service" "attendance-service"
run_service_migration "storage-service" "storage-service"
run_service_migration "notification-service" "notification-service"
run_service_migration "leave-service" "leave-service"

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
  "$PYTHON_BIN" run.py
) &
auth_pid=$!

(
  cd "$ROOT_DIR/attendance-service"
  "$PYTHON_BIN" run.py
) &
attendance_pid=$!

(
  cd "$ROOT_DIR/storage-service"
  "$PYTHON_BIN" run.py
) &
storage_pid=$!

(
  cd "$ROOT_DIR/notification-service"
  "$PYTHON_BIN" run.py
) &
notification_pid=$!

(
  cd "$ROOT_DIR/leave-service"
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
