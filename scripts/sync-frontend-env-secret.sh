#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${FRONTEND_ENV_FILE:-$ROOT_DIR/attendio-frontend/.env}"
REPO="${GITHUB_FRONTEND_REPO:-mbilalhussain04/attendio-frontend}"
SECRET_NAME="${GITHUB_FRONTEND_ENV_SECRET_NAME:-VPS_FRONTEND_ENV_B64}"
RENDERED_ENV_FILE=""

cleanup() {
  if [ -n "$RENDERED_ENV_FILE" ] && [ -f "$RENDERED_ENV_FILE" ]; then
    rm -f "$RENDERED_ENV_FILE"
  fi
}
trap cleanup EXIT

if ! command -v gh >/dev/null 2>&1; then
  echo "GitHub CLI is required. Install it, then run: gh auth login" >&2
  exit 1
fi

if ! gh auth status >/dev/null 2>&1; then
  echo "GitHub CLI is not logged in. Run: gh auth login" >&2
  exit 1
fi

if [ ! -f "$ENV_FILE" ]; then
  echo "Frontend env file not found: $ENV_FILE" >&2
  exit 1
fi

RENDERED_ENV_FILE="$(mktemp)"
awk -F= '
  BEGIN {
    api = "https://api.attendio.technoflick.com/api/v1"
    console = "false"
  }
  /^PROD_VITE_API_BASE_URL=/ { api = substr($0, index($0, "=") + 1) }
  /^PROD_VITE_ENABLE_AUTH_API_CONSOLE=/ { console = substr($0, index($0, "=") + 1) }
  END {
    print "VITE_API_BASE_URL=" api
    print "VITE_ENABLE_AUTH_API_CONSOLE=" console
  }
' "$ENV_FILE" > "$RENDERED_ENV_FILE"

encoded="$(base64 < "$RENDERED_ENV_FILE" | tr -d '\n')"
if [ -z "$encoded" ]; then
  echo "Rendered frontend env is empty." >&2
  exit 1
fi

gh secret set "$SECRET_NAME" --repo "$REPO" --body "$encoded"
echo "Updated GitHub secret $SECRET_NAME for $REPO from production render of $ENV_FILE"
