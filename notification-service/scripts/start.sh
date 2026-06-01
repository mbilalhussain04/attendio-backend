#!/usr/bin/env sh
set -e
alembic upgrade head
python run.py
