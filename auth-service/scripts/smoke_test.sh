#!/usr/bin/env sh
set -e
BASE_URL=${BASE_URL:-http://localhost:8000/api/v1}

curl -s "$BASE_URL/health"
echo
curl -s -X POST "$BASE_URL/auth/bootstrap-company" \
  -H 'Content-Type: application/json' \
  -d '{"company_name":"Attendio Demo","owner_first_name":"Owner","owner_last_name":"Admin","owner_email":"owner@example.com","owner_password":"Admin@12345"}'
echo
