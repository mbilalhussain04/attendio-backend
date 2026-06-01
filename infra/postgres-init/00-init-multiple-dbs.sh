#!/bin/bash
set -e
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" <<-EOSQL
  CREATE DATABASE attendio_auth;
  CREATE DATABASE attendio_attendance;
  CREATE DATABASE attendio_storage;
  CREATE DATABASE attendio_leave;
  CREATE DATABASE attendio_billing;
EOSQL
