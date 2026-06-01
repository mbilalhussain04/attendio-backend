import os
import sys
from urllib.parse import urlparse
from urllib.parse import quote

import psycopg
import urllib.request


def env(name: str, default: str) -> str:
    return os.environ.get(name) or default


def server_url(database: str = "postgres") -> str:
    user = env("POSTGRES_USER", "postgres")
    password = os.environ.get("POSTGRES_PASSWORD", "")
    host = env("POSTGRES_HOST", "localhost")
    port = env("POSTGRES_PORT", "5432")
    auth = quote(user)
    if password:
        auth = f"{auth}:{quote(password)}"
    return f"postgresql://{auth}@{host}:{port}/{database}"


def ensure_database(name: str) -> None:
    try:
        with psycopg.connect(server_url(), autocommit=True) as conn:
            exists = conn.execute(
                "select 1 from pg_database where datname = %s",
                (name,),
            ).fetchone()
            if not exists:
                conn.execute(f'create database "{name}"')
                print(f"Created PostgreSQL database: {name}")
    except psycopg.OperationalError as exc:
        host = env("POSTGRES_HOST", "localhost")
        port = env("POSTGRES_PORT", "5432")
        user = env("POSTGRES_USER", "postgres")
        print(
            f"PostgreSQL is not reachable at {host}:{port}. "
            f"Start PostgreSQL locally and make sure role `{user}` can connect, "
            "then run `make local` again.",
            file=sys.stderr,
        )
        print(f"Driver error: {exc}", file=sys.stderr)
        sys.exit(1)


def check_redis() -> None:
    try:
        import redis
    except ImportError:
        return

    redis_url = env("REDIS_URL", "redis://localhost:6379/0")
    parsed = urlparse(redis_url)
    try:
        redis.Redis.from_url(redis_url).ping()
    except redis.RedisError:
        print(
            f"Redis is not responding at {parsed.hostname or 'localhost'}:{parsed.port or 6379}. "
            "The services can start, but login/session/event flows may fail.",
            file=sys.stderr,
        )


def check_minio() -> None:
    if env("STORAGE_BACKEND", "auto").lower() == "local":
        return
    endpoint = env("MINIO_ENDPOINT", "localhost:9000")
    scheme = "https" if env("MINIO_SECURE", "false").lower() == "true" else "http"
    try:
        urllib.request.urlopen(f"{scheme}://{endpoint}/minio/health/live", timeout=2)
    except Exception:
        print(
            f"MinIO is not responding at {scheme}://{endpoint}. "
            "Storage will use the local filesystem fallback while STORAGE_BACKEND=auto.",
            file=sys.stderr,
        )


if __name__ == "__main__":
    ensure_database(env("AUTH_DB_NAME", "attendio_auth"))
    ensure_database(env("ATTENDANCE_DB_NAME", "attendio_attendance"))
    ensure_database(env("STORAGE_DB_NAME", "attendio_storage"))
    ensure_database(env("NOTIFICATION_DB_NAME", "attendio_notification"))
    ensure_database(env("LEAVE_DB_NAME", "attendio_leave"))
    ensure_database(env("BILLING_DB_NAME", "attendio_billing"))
    check_redis()
    check_minio()
