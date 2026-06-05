#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${FRONTEND_ENV_FILE:-$ROOT_DIR/attendio-frontend/.env}"
REPO="${GITHUB_FRONTEND_REPO:-mbilalhussain04/attendio-frontend}"
SECRET_NAME="${GITHUB_FRONTEND_ENV_SECRET_NAME:-VPS_FRONTEND_ENV_B64}"

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

encoded="$(base64 < "$ENV_FILE" | tr -d '\n')"
if [ -z "$encoded" ]; then
  echo "Frontend env file is empty: $ENV_FILE" >&2
  exit 1
fi

gh secret set "$SECRET_NAME" --repo "$REPO" --body "$encoded"
echo "Updated GitHub secret $SECRET_NAME for $REPO from $ENV_FILE"
