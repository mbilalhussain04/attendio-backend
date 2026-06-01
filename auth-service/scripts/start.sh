#!/usr/bin/env sh
set -e
alembic upgrade head
python -m app.seed.bootstrap
uvicorn app.main:app --host 0.0.0.0 --port 8000
