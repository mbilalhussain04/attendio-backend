#!/usr/bin/env sh
set -e
base_url=${1:-http://localhost}
echo "Checking docs gateway..."
curl -fsS "$base_url/docs" >/dev/null
echo "Checking auth health..."
curl -fsS "$base_url/api/v1/health" >/dev/null
echo "Checking attendance health..."
curl -fsS "$base_url/api/v1/attendance/health" >/dev/null || curl -fsS "http://localhost:8001/health" >/dev/null
echo "Checking leave health..."
curl -fsS "$base_url/api/v1/leave/health" >/dev/null || curl -fsS "http://localhost:8004/health" >/dev/null
echo "Smoke checks passed."
