#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${BACKEND_ENV_FILE:-$ROOT_DIR/.env}"
REPO="${GITHUB_REPO:-mbilalhussain04/attendio-backend}"
SECRET_NAME="${GITHUB_ENV_SECRET_NAME:-VPS_BACKEND_ENV_B64}"

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

app_env="$(grep -E '^APP_ENV=' "$ENV_FILE" | tail -1 | cut -d= -f2- | tr -d '"' || true)"
if [ "${ALLOW_NON_PRODUCTION_ENV_SYNC:-false}" != "true" ] && [ "$app_env" != "production" ]; then
  echo "Refusing to sync $ENV_FILE because APP_ENV='$app_env'." >&2
  echo "VPS_BACKEND_ENV_B64 must contain a production env. Set ALLOW_NON_PRODUCTION_ENV_SYNC=true only for a temporary test VPS." >&2
  exit 1
fi

encoded="$(base64 < "$ENV_FILE" | tr -d '\n')"
if [ -z "$encoded" ]; then
  echo "Backend env file is empty: $ENV_FILE" >&2
  exit 1
fi

gh secret set "$SECRET_NAME" --repo "$REPO" --body "$encoded"
echo "Updated GitHub secret $SECRET_NAME for $REPO from $ENV_FILE"
