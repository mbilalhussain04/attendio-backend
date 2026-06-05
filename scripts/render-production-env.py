#!/usr/bin/env python3
"""Render a production env from the single backend .env file.

Local development keeps using .env directly. GitHub Actions/VPS deploys use the
rendered output from this script so the repository has one editable env file,
without accidentally shipping localhost/development values to production.
"""

from __future__ import annotations

import argparse
import secrets
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def token() -> str:
    return secrets.token_hex(32)


def parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def write_secret_additions(path: Path, additions: dict[str, str]) -> None:
    if not additions:
        return
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n# Production deploy values. Local runtime ignores these PROD_* keys.\n")
        for key, value in additions.items():
            handle.write(f"{key}={value}\n")
    path.chmod(0o600)


def ensure_prod_value(
    values: dict[str, str],
    additions: dict[str, str],
    key: str,
    fallback: str | None = None,
    legacy_values: dict[str, str] | None = None,
) -> str:
    prod_key = f"PROD_{key}"
    if values.get(prod_key):
        return values[prod_key]
    if legacy_values and legacy_values.get(key):
        values[prod_key] = legacy_values[key]
        additions[prod_key] = legacy_values[key]
        return legacy_values[key]
    if fallback is not None:
        values[prod_key] = fallback
        additions[prod_key] = fallback
        return fallback
    generated = token()
    values[prod_key] = generated
    additions[prod_key] = generated
    return generated


def env_line(key: str, value: str) -> str:
    return f"{key}={value}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Render Attendio production env from .env")
    parser.add_argument("--env-file", default=str(ROOT / ".env"))
    parser.add_argument("--ensure-secrets", action="store_true")
    args = parser.parse_args()

    env_file = Path(args.env_file)
    if not env_file.exists():
        raise SystemExit(f"Backend env file not found: {env_file}")

    values = parse_env(env_file)
    legacy_values = parse_env(ROOT / ".env.production")
    additions: dict[str, str] = {}

    root_domain = values.get("PROD_ROOT_DOMAIN") or legacy_values.get("DEFAULT_ROOT_DOMAIN") or "attendio.technoflick.com"
    frontend_url = (values.get("PROD_FRONTEND_BASE_URL") or legacy_values.get("FRONTEND_BASE_URL") or f"https://{root_domain}").rstrip("/")
    api_domain = values.get("PROD_API_DOMAIN") or legacy_values.get("AUTH_BASE_DOMAIN") or f"api.{root_domain}"
    api_url = (values.get("PROD_API_BASE_URL") or legacy_values.get("GATEWAY_PUBLIC_URL") or f"https://{api_domain}").rstrip("/")
    postgres_user = values.get("PROD_POSTGRES_USER") or legacy_values.get("POSTGRES_USER") or "attendio"
    rabbitmq_user = values.get("PROD_RABBITMQ_DEFAULT_USER") or legacy_values.get("RABBITMQ_DEFAULT_USER") or "attendio"

    if args.ensure_secrets:
        postgres_password = ensure_prod_value(values, additions, "POSTGRES_PASSWORD", legacy_values=legacy_values)
        rabbitmq_password = ensure_prod_value(values, additions, "RABBITMQ_DEFAULT_PASS", legacy_values=legacy_values)
        minio_access_key = ensure_prod_value(
            values,
            additions,
            "MINIO_ACCESS_KEY",
            f"attendio-{secrets.token_hex(8)}",
            legacy_values,
        )
        minio_secret_key = ensure_prod_value(values, additions, "MINIO_SECRET_KEY", legacy_values=legacy_values)
        secret_key = ensure_prod_value(values, additions, "SECRET_KEY", legacy_values=legacy_values)
        jwt_secret = ensure_prod_value(values, additions, "JWT_ACCESS_SECRET", legacy_values=legacy_values)
        internal_token = ensure_prod_value(values, additions, "INTERNAL_SERVICE_TOKEN", legacy_values=legacy_values)
        write_secret_additions(env_file, additions)
    else:
        required = [
            "PROD_POSTGRES_PASSWORD",
            "PROD_RABBITMQ_DEFAULT_PASS",
            "PROD_MINIO_SECRET_KEY",
            "PROD_SECRET_KEY",
            "PROD_JWT_ACCESS_SECRET",
            "PROD_INTERNAL_SERVICE_TOKEN",
        ]
        missing = [key for key in required if not values.get(key)]
        if missing:
            raise SystemExit(
                "Missing production values in .env: "
                + ", ".join(missing)
                + ". Re-run with --ensure-secrets or run make sync-env."
            )
        postgres_password = values["PROD_POSTGRES_PASSWORD"]
        rabbitmq_password = values["PROD_RABBITMQ_DEFAULT_PASS"]
        minio_access_key = values.get("PROD_MINIO_ACCESS_KEY") or "attendio-minio"
        minio_secret_key = values["PROD_MINIO_SECRET_KEY"]
        secret_key = values["PROD_SECRET_KEY"]
        jwt_secret = values["PROD_JWT_ACCESS_SECRET"]
        internal_token = values["PROD_INTERNAL_SERVICE_TOKEN"]

    production = dict(values)
    for key, value in legacy_values.items():
        if not key.startswith("PROD_") and (key not in production or production[key] == ""):
            production[key] = value
    production.update(
        {
            "COMPOSE_PROJECT_NAME": values.get("COMPOSE_PROJECT_NAME", "attendio-platform"),
            "GATEWAY_BIND": "127.0.0.1",
            "GATEWAY_PORT": "8080",
            "INFRA_BIND": "127.0.0.1",
            "POSTGRES_USER": postgres_user,
            "POSTGRES_PASSWORD": postgres_password,
            "POSTGRES_HOST": "platform-postgres",
            "POSTGRES_PORT": "5432",
            "AUTH_DATABASE_URL": f"postgresql+psycopg://{postgres_user}:{postgres_password}@platform-postgres:5432/{values.get('AUTH_DB_NAME', 'attendio_auth')}",
            "ATTENDANCE_DATABASE_URL": f"postgresql+psycopg://{postgres_user}:{postgres_password}@platform-postgres:5432/{values.get('ATTENDANCE_DB_NAME', 'attendio_attendance')}",
            "STORAGE_DATABASE_URL": f"postgresql+psycopg://{postgres_user}:{postgres_password}@platform-postgres:5432/{values.get('STORAGE_DB_NAME', 'attendio_storage')}",
            "NOTIFICATION_DATABASE_URL": f"postgresql+psycopg://{postgres_user}:{postgres_password}@platform-postgres:5432/{values.get('NOTIFICATION_DB_NAME', 'attendio_notification')}",
            "LEAVE_DATABASE_URL": f"postgresql+psycopg://{postgres_user}:{postgres_password}@platform-postgres:5432/{values.get('LEAVE_DB_NAME', 'attendio_leave')}",
            "BILLING_DATABASE_URL": f"postgresql+psycopg://{postgres_user}:{postgres_password}@platform-postgres:5432/{values.get('BILLING_DB_NAME', 'attendio_billing')}",
            "REDIS_URL": "redis://redis:6379/0",
            "RABBITMQ_DEFAULT_USER": rabbitmq_user,
            "RABBITMQ_DEFAULT_PASS": rabbitmq_password,
            "RABBITMQ_URL": f"amqp://{rabbitmq_user}:{rabbitmq_password}@rabbitmq:5672/",
            "APP_ENV": "production",
            "DEBUG": "false",
            "SECRET_KEY": secret_key,
            "JWT_ACCESS_SECRET": jwt_secret,
            "INTERNAL_SERVICE_TOKEN": internal_token,
            "COOKIE_SECURE": "true",
            "COOKIE_DOMAIN": f".{root_domain}",
            "DEFAULT_ROOT_DOMAIN": root_domain,
            "AUTH_BASE_DOMAIN": api_domain,
            "BASE_DOMAIN": root_domain,
            "FRONTEND_BASE_URL": frontend_url,
            "AUTH_SERVICE_URL": "http://auth-service:8000",
            "ATTENDANCE_SERVICE_URL": "http://attendance-service:8001",
            "STORAGE_SERVICE_URL": "http://storage-service:8002",
            "NOTIFICATION_SERVICE_URL": "http://notification-service:8003",
            "LEAVE_SERVICE_URL": "http://leave-service:8004",
            "BILLING_SERVICE_URL": "http://billing-service:8005",
            "DOCS_GATEWAY_URL": "http://docs-gateway:8090",
            "GATEWAY_PUBLIC_URL": api_url,
            "PUBLIC_AUTH_API_URL": api_url,
            "PUBLIC_ATTENDANCE_API_URL": api_url,
            "PUBLIC_STORAGE_API_URL": api_url,
            "PUBLIC_NOTIFICATION_API_URL": api_url,
            "PUBLIC_LEAVE_API_URL": api_url,
            "PUBLIC_BILLING_API_URL": api_url,
            "CORS_ORIGINS": f"{frontend_url},{api_url}",
            "MINIO_ENDPOINT": "minio:9000",
            "MINIO_ACCESS_KEY": minio_access_key,
            "MINIO_SECRET_KEY": minio_secret_key,
            "MINIO_SECURE": "false",
            "STORAGE_BACKEND": "minio",
            "PUBLIC_STORAGE_BASE_URL": f"{api_url}/api/v1/storage/files",
            "OAUTH_REDIRECT_URI": f"{api_url}/api/v1/auth/sso/callback",
            "SMTP_FROM": values.get("SMTP_FROM") or f"no-reply@{root_domain}",
            "BILLING_SUCCESS_URL": f"{frontend_url}/settings?tab=billing&billing=success",
            "BILLING_CANCEL_URL": f"{frontend_url}/settings?tab=billing&billing=cancelled",
        }
    )

    ordered_keys: list[str] = []
    for raw_line in (ROOT / ".env.example").read_text().splitlines():
        line = raw_line.strip()
        if line and not line.startswith("#") and "=" in line:
            key = line.split("=", 1)[0].strip()
            if key and not key.startswith("PROD_") and key not in ordered_keys:
                ordered_keys.append(key)

    for key in production:
        if key.startswith("PROD_"):
            continue
        if key not in ordered_keys:
            ordered_keys.append(key)

    print("\n".join(env_line(key, production.get(key, "")) for key in ordered_keys))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
