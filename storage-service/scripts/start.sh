#!/usr/bin/env sh
set -e
python -m alembic upgrade head
exec python run.py
