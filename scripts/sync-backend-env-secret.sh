#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${BACKEND_ENV_FILE:-$ROOT_DIR/.env}"
REPO="${GITHUB_REPO:-mbilalhussain04/attendio-backend}"
SECRET_NAME="${GITHUB_ENV_SECRET_NAME:-VPS_BACKEND_ENV_B64}"
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
  echo "Backend env file not found: $ENV_FILE" >&2
  exit 1
fi

RENDERED_ENV_FILE="$(mktemp)"
python3 "$ROOT_DIR/scripts/render-production-env.py" --env-file "$ENV_FILE" --ensure-secrets > "$RENDERED_ENV_FILE"

app_env="$(grep -E '^APP_ENV=' "$RENDERED_ENV_FILE" | tail -1 | cut -d= -f2- | tr -d '"' || true)"
if [ "$app_env" != "production" ]; then
  echo "Rendered production env is invalid: APP_ENV='$app_env'." >&2
  exit 1
fi

encoded="$(base64 < "$RENDERED_ENV_FILE" | tr -d '\n')"
if [ -z "$encoded" ]; then
  echo "Rendered backend env is empty." >&2
  exit 1
fi

gh secret set "$SECRET_NAME" --repo "$REPO" --body "$encoded"
echo "Updated GitHub secret $SECRET_NAME for $REPO from production render of $ENV_FILE"
