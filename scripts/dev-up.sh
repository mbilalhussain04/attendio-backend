#!/usr/bin/env sh
set -e
docker compose up --build -d
docker compose ps
