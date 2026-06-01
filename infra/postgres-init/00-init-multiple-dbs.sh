#!/bin/bash
set -e

create_database() {
  local database="$1"
  if [ -z "$database" ]; then
    return
  fi

  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    SELECT 'CREATE DATABASE "$database"'
    WHERE NOT EXISTS (
      SELECT FROM pg_database WHERE datname = '$database'
    )\gexec
EOSQL
}

create_database "${AUTH_DB_NAME:-attendio_auth}"
create_database "${ATTENDANCE_DB_NAME:-attendio_attendance}"
create_database "${STORAGE_DB_NAME:-attendio_storage}"
create_database "${NOTIFICATION_DB_NAME:-attendio_notification}"
create_database "${LEAVE_DB_NAME:-attendio_leave}"
create_database "${BILLING_DB_NAME:-attendio_billing}"
