#!/usr/bin/env python3
"""Create a production .env file without committing secrets."""

from __future__ import annotations

import argparse
import secrets
from pathlib import Path


def token() -> str:
    return secrets.token_hex(32)


def set_value(lines: list[str], key: str, value: str) -> None:
    prefix = f"{key}="
    for index, line in enumerate(lines):
        if line.startswith(prefix):
            lines[index] = f"{key}={value}"
            return
    lines.append(f"{key}={value}")


def parse_env(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Attendio production .env")
    parser.add_argument("--frontend-url", default="https://attendio.technoflick.com")
    parser.add_argument("--api-url", default="https://api.attendio.technoflick.com")
    parser.add_argument("--root-domain", default="attendio.technoflick.com")
    parser.add_argument("--output", default=".env")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    template = root / ".env.example"
    output = root / args.output
    local_values = parse_env(root / ".env")

    if output.exists() and not args.force:
        raise SystemExit(f"{output} already exists. Re-run with --force to replace it.")

    postgres_password = token()
    rabbitmq_password = token()
    minio_access_key = f"attendio-{secrets.token_hex(8)}"
    minio_secret_key = token()

    lines = template.read_text().splitlines()
    api_host = args.api_url.removeprefix("https://").removeprefix("http://").rstrip("/")
    frontend_url = args.frontend_url.rstrip("/")
    api_url = args.api_url.rstrip("/")

    production_values = {
        "GATEWAY_BIND": "127.0.0.1",
        "GATEWAY_PORT": "8080",
        "INFRA_BIND": "127.0.0.1",
        "POSTGRES_USER": "attendio",
        "POSTGRES_PASSWORD": postgres_password,
        "POSTGRES_HOST": "platform-postgres",
        "AUTH_DATABASE_URL": f"postgresql+psycopg://attendio:{postgres_password}@platform-postgres:5432/attendio_auth",
        "ATTENDANCE_DATABASE_URL": f"postgresql+psycopg://attendio:{postgres_password}@platform-postgres:5432/attendio_attendance",
        "STORAGE_DATABASE_URL": f"postgresql+psycopg://attendio:{postgres_password}@platform-postgres:5432/attendio_storage",
        "NOTIFICATION_DATABASE_URL": f"postgresql+psycopg://attendio:{postgres_password}@platform-postgres:5432/attendio_notification",
        "LEAVE_DATABASE_URL": f"postgresql+psycopg://attendio:{postgres_password}@platform-postgres:5432/attendio_leave",
        "BILLING_DATABASE_URL": f"postgresql+psycopg://attendio:{postgres_password}@platform-postgres:5432/attendio_billing",
        "REDIS_URL": "redis://redis:6379/0",
        "RABBITMQ_DEFAULT_USER": "attendio",
        "RABBITMQ_DEFAULT_PASS": rabbitmq_password,
        "RABBITMQ_URL": f"amqp://attendio:{rabbitmq_password}@rabbitmq:5672/",
        "APP_ENV": "production",
        "DEBUG": "false",
        "SECRET_KEY": token(),
        "JWT_ACCESS_SECRET": token(),
        "INTERNAL_SERVICE_TOKEN": token(),
        "COOKIE_SECURE": "true",
        "COOKIE_DOMAIN": f".{args.root_domain}",
        "DEFAULT_ROOT_DOMAIN": args.root_domain,
        "AUTH_BASE_DOMAIN": api_host,
        "BASE_DOMAIN": args.root_domain,
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
        "PUBLIC_STORAGE_BASE_URL": f"{api_url}/api/v1/storage/files",
        "CORS_ORIGINS": f"{frontend_url},{api_url}",
        "MINIO_ENDPOINT": "minio:9000",
        "MINIO_ACCESS_KEY": minio_access_key,
        "MINIO_SECRET_KEY": minio_secret_key,
        "STORAGE_BACKEND": "minio",
        "OAUTH_REDIRECT_URI": f"{api_url}/api/v1/auth/sso/callback",
        "SSO_AUTO_PROVISION": "false",
        "SMTP_FROM": f"no-reply@{args.root_domain}",
        "BILLING_SUCCESS_URL": f"{frontend_url}/settings?tab=billing&billing=success",
        "BILLING_CANCEL_URL": f"{frontend_url}/settings?tab=billing&billing=cancelled",
    }
    provider_keys = [
        "GOOGLE_CLIENT_ID",
        "GOOGLE_CLIENT_SECRET",
        "MICROSOFT_CLIENT_ID",
        "MICROSOFT_CLIENT_SECRET",
        "SMTP_HOST",
        "SMTP_PORT",
        "SMTP_USERNAME",
        "SMTP_PASSWORD",
        "SMTP_USE_TLS",
        "STRIPE_SECRET_KEY",
        "STRIPE_WEBHOOK_SECRET",
        "STRIPE_PRICE_STANDARD",
        "PAYONEER_CLIENT_ID",
        "PAYONEER_CLIENT_SECRET",
        "PAYONEER_WEBHOOK_SECRET",
    ]
    for key in provider_keys:
        value = local_values.get(key)
        if value:
            production_values[key] = value

    for key, value in production_values.items():
        set_value(lines, key, value)

    output.write_text("\n".join(lines).rstrip() + "\n")
    output.chmod(0o600)

    print(f"Wrote {output}")
    print("Review OAuth, SMTP, Stripe/Payoneer values before opening production to users.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
