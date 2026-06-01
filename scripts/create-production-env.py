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


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Attendio production .env")
    parser.add_argument("--frontend-url", default="https://attendio.technoflick.com")
    parser.add_argument("--api-url", default="https://api.attendio.technoflick.com")
    parser.add_argument("--root-domain", default="attendio.technoflick.com")
    parser.add_argument("--output", default=".env")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    template = root / ".env.production.example"
    output = root / args.output

    if output.exists() and not args.force:
        raise SystemExit(f"{output} already exists. Re-run with --force to replace it.")

    postgres_password = token()
    rabbitmq_password = token()
    minio_access_key = f"attendio-{secrets.token_hex(8)}"
    minio_secret_key = token()

    text = template.read_text()
    replacements = {
        "replace-with-a-long-random-password": postgres_password,
        "replace-rabbitmq-password": rabbitmq_password,
        "replace-with-64-random-characters": token(),
        "replace-with-another-64-random-characters": token(),
        "replace-with-another-long-random-token": token(),
        "replace-minio-access-key": minio_access_key,
        "replace-minio-secret-key": minio_secret_key,
        "https://attendio.technoflick.com": args.frontend_url.rstrip("/"),
        "https://api.attendio.technoflick.com": args.api_url.rstrip("/"),
        "attendio.technoflick.com": args.root_domain,
        ".attendio.technoflick.com": f".{args.root_domain}",
        "api.attendio.technoflick.com": args.api_url.removeprefix("https://").removeprefix("http://").rstrip("/"),
    }
    for old, new in replacements.items():
        text = text.replace(old, new)

    lines = text.splitlines()
    set_value(lines, "POSTGRES_PASSWORD", postgres_password)
    set_value(lines, "RABBITMQ_DEFAULT_USER", "attendio")
    set_value(lines, "RABBITMQ_DEFAULT_PASS", rabbitmq_password)

    output.write_text("\n".join(lines).rstrip() + "\n")
    output.chmod(0o600)

    print(f"Wrote {output}")
    print("Review OAuth, SMTP, Stripe/Payoneer values before opening production to users.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
