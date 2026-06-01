from pathlib import Path
root = Path('/mnt/data/attendio-fastapi-postgres-final')
files = {}

def add(path, content):
    files[path] = content.lstrip('\n')

add('requirements.txt', '''
fastapi==0.115.0
uvicorn[standard]==0.30.6
sqlalchemy==2.0.36
psycopg[binary]==3.2.3
alembic==1.13.3
pydantic[email]==2.9.2
pydantic-settings==2.5.2
python-jose[cryptography]==3.3.0
passlib[bcrypt]==1.7.4
bcrypt==4.2.0
python-multipart==0.0.12
pyotp==2.9.0
python-slugify==8.0.4
pandas==2.2.3
openpyxl==3.1.5
redis==5.1.1
authlib==1.3.2
itsdangerous==2.2.0
prometheus-client==0.21.0
''')

add('.env.example', '''
APP_NAME=Attendio Auth Service
APP_ENV=development
API_V1_PREFIX=/api/v1
SECRET_KEY=change-this-in-production
ACCESS_TOKEN_EXPIRE_MINUTES=15
REFRESH_TOKEN_EXPIRE_DAYS=30
PASSWORD_RESET_EXPIRE_MINUTES=30
EMAIL_VERIFICATION_EXPIRE_HOURS=24
COOKIE_SECURE=false
COOKIE_DOMAIN=
SESSION_COOKIE_NAME=attendio_session
REFRESH_COOKIE_NAME=attendio_refresh
DEFAULT_ROOT_DOMAIN=lvh.me
AUTH_BASE_DOMAIN=auth.lvh.me
FRONTEND_AFTER_LOGIN=/dashboard
ALLOW_EMAIL_LOGIN_FALLBACK=true
LOGIN_MAX_ATTEMPTS=5
LOGIN_LOCK_MINUTES=15
DATABASE_URL=postgresql+psycopg://postgres:postgres@postgres:5432/attendio_auth
REDIS_URL=redis://redis:6379/0
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
MICROSOFT_CLIENT_ID=
MICROSOFT_CLIENT_SECRET=
OAUTH_REDIRECT_URI=http://auth.lvh.me/api/v1/auth/sso/callback
SMTP_HOST=
SMTP_PORT=587
SMTP_USERNAME=
SMTP_PASSWORD=
SMTP_FROM=no-reply@attendio.local
''')

add('run.py', '''
import uvicorn

if __name__ == '__main__':
    uvicorn.run('app.main:app', host='0.0.0.0', port=8000, reload=True)
''')

add('Dockerfile', '''
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends build-essential curl && rm -rf /var/lib/apt/lists/*
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["sh", "scripts/start.sh"]
''')

add('docker-compose.yml', '''
version: '3.9'
services:
  nginx:
    image: nginx:1.27-alpine
    depends_on:
      - auth-service
    ports:
      - '80:80'
    volumes:
      - ./nginx/default.conf:/etc/nginx/conf.d/default.conf:ro

  auth-service:
    build: .
    env_file:
      - .env
    expose:
      - '8000'
    ports:
      - '8000:8000'
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy

  postgres:
    image: postgres:16
    environment:
      POSTGRES_DB: attendio_auth
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
    ports:
      - '5432:5432'
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ['CMD-SHELL', 'pg_isready -U postgres -d attendio_auth']
      interval: 10s
      timeout: 5s
      retries: 20

  redis:
    image: redis:7-alpine
    ports:
      - '6379:6379'
    healthcheck:
      test: ['CMD', 'redis-cli', 'ping']
      interval: 10s
      timeout: 5s
      retries: 20

volumes:
  pgdata:
''')

add('nginx/default.conf', '''
upstream attendio_auth_backend {
  server auth-service:8000;
  keepalive 64;
}

server {
  listen 80 default_server;
  server_name _;
  client_max_body_size 25m;

  location = /nginx-health {
    access_log off;
    add_header Content-Type text/plain;
    return 200 'ok';
  }

  location / {
    proxy_pass http://attendio_auth_backend;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header Connection '';
    proxy_read_timeout 120s;
    proxy_connect_timeout 15s;
    proxy_send_timeout 120s;
    proxy_buffering off;
  }
}
''')

add('scripts/start.sh', '''
#!/usr/bin/env sh
set -e
alembic upgrade head
python -m app.seed.bootstrap
uvicorn app.main:app --host 0.0.0.0 --port 8000
''')

add('README.md', '''
# Attendio Auth FastAPI Final

PostgreSQL based tenant-aware auth microservice for Attendio, converted to FastAPI with Swagger tags, Alembic migrations, and domain based tenant isolation.

## What is included

- FastAPI with categorized Swagger tags
- PostgreSQL models and Alembic migrations
- Tenant aware login using tenant domain or unique email fallback
- Auto slug and auto tenant domain on company bootstrap
- JWT access and refresh flow with HttpOnly cookies
- MFA setup and verify with TOTP
- Google and Microsoft SSO route placeholders with provider wiring
- Roles, permissions, sessions, audit logs, API keys
- Employee create, bulk create, CSV or XLSX import, template download
- Kiosk pin and kiosk login
- Nginx reverse proxy preserving host for multi tenant domain routing

## Bootstrap behavior

`POST /api/v1/auth/bootstrap-company` only needs:

```json
{
  "company_name": "Attendio Demo",
  "owner_first_name": "Owner",
  "owner_last_name": "Admin",
  "owner_email": "owner@example.com",
  "owner_password": "Admin@12345"
}
```

The backend auto generates:

- `slug` from company name
- `domain` like `attendio-demo.lvh.me`
- owner employee code like `EMP-000001`

## Login behavior

Login only needs:

```json
{
  "email": "owner@example.com",
  "password": "Admin@12345"
}
```

How tenant is resolved:

1. current request host like `attendio-demo.lvh.me`
2. forwarded host from nginx
3. tenant cookies
4. unique email fallback across companies

If the same email exists in multiple companies, backend rejects global login and asks the client to use the tenant domain. This avoids accidental cross tenant access.

## Swagger categories

- Health
- Authentication
- MFA
- SSO
- Sessions
- Roles & Permissions
- Employees
- API Keys
- Audit Logs
- Kiosk

## Run locally

```bash
cp .env.example .env
pip install -r requirements.txt
alembic upgrade head
python -m app.seed.bootstrap
python run.py
```

Open:

- Direct app: `http://localhost:8000/docs`
- Behind nginx with tenant host: `http://auth.lvh.me/docs`

## Docker

```bash
docker compose down -v
docker compose up --build
```

## Multi tenant access examples

- Auth root docs: `http://auth.lvh.me/docs`
- Tenant health: `http://attendio-demo.lvh.me/api/v1/health`
- Tenant login from nginx preserves host so backend resolves the tenant correctly.

## Important note about Google and Microsoft login

The routes are implemented and categorized in Swagger, but you must set provider credentials in `.env` for real redirects and callback exchange. Without credentials the endpoints return a clear configuration error instead of silently failing.
''')

# app files
add('app/__init__.py', '')
add('app/main.py', '''
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from prometheus_client import make_asgi_app

from app.api.api import api_router
from app.core.config import settings
from app.db.session import engine
from app.models import base  # noqa
from app.middleware.tenant import TenantMiddleware
from app.seed.bootstrap import ensure_seed_data

TAGS_METADATA = [
    {"name": "Health", "description": "Health checks and metrics."},
    {"name": "Authentication", "description": "Bootstrap company, login, refresh, me, email verification, password reset, impersonation."},
    {"name": "MFA", "description": "TOTP MFA setup and verify endpoints."},
    {"name": "SSO", "description": "Google and Microsoft SSO entry and callback endpoints."},
    {"name": "Sessions", "description": "Current sessions and revocation."},
    {"name": "Roles & Permissions", "description": "Read permissions, roles, and create custom roles."},
    {"name": "Employees", "description": "Single create, bulk create, import, template download, list and detail."},
    {"name": "API Keys", "description": "Issue and revoke tenant scoped API keys."},
    {"name": "Audit Logs", "description": "Tenant scoped audit trail."},
    {"name": "Kiosk", "description": "Kiosk pin and kiosk login."},
]

@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_seed_data()
    yield

app = FastAPI(
    title=settings.APP_NAME,
    version='1.0.0',
    openapi_tags=TAGS_METADATA,
    docs_url='/docs',
    redoc_url='/redoc',
    lifespan=lifespan,
)
app.add_middleware(SessionMiddleware, secret_key=settings.SECRET_KEY)
app.add_middleware(TenantMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_methods=['*'],
    allow_headers=['*'],
    allow_credentials=True,
)
app.include_router(api_router, prefix=settings.API_V1_PREFIX)
app.mount('/metrics', make_asgi_app())
''')

add('app/core/config.py', '''
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', case_sensitive=True, extra='ignore')

    APP_NAME: str = 'Attendio Auth Service'
    APP_ENV: str = 'development'
    API_V1_PREFIX: str = '/api/v1'
    SECRET_KEY: str = 'change-me'
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    PASSWORD_RESET_EXPIRE_MINUTES: int = 30
    EMAIL_VERIFICATION_EXPIRE_HOURS: int = 24
    COOKIE_SECURE: bool = False
    COOKIE_DOMAIN: str | None = None
    SESSION_COOKIE_NAME: str = 'attendio_session'
    REFRESH_COOKIE_NAME: str = 'attendio_refresh'
    DEFAULT_ROOT_DOMAIN: str = 'lvh.me'
    AUTH_BASE_DOMAIN: str = 'auth.lvh.me'
    FRONTEND_AFTER_LOGIN: str = '/dashboard'
    ALLOW_EMAIL_LOGIN_FALLBACK: bool = True
    LOGIN_MAX_ATTEMPTS: int = 5
    LOGIN_LOCK_MINUTES: int = 15
    DATABASE_URL: str = 'postgresql+psycopg://postgres:postgres@localhost:5432/attendio_auth'
    REDIS_URL: str = 'redis://localhost:6379/0'
    GOOGLE_CLIENT_ID: str | None = None
    GOOGLE_CLIENT_SECRET: str | None = None
    MICROSOFT_CLIENT_ID: str | None = None
    MICROSOFT_CLIENT_SECRET: str | None = None
    OAUTH_REDIRECT_URI: str = 'http://auth.lvh.me/api/v1/auth/sso/callback'
    SMTP_HOST: str | None = None
    SMTP_PORT: int = 587
    SMTP_USERNAME: str | None = None
    SMTP_PASSWORD: str | None = None
    SMTP_FROM: str = 'no-reply@attendio.local'

settings = Settings()
''')

add('app/core/security.py', '''
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from jose import jwt, JWTError
from passlib.context import CryptContext
from slugify import slugify as _slugify
import secrets

from app.core.config import settings

pwd_context = CryptContext(schemes=['bcrypt'], deprecated='auto')
ALGORITHM = 'HS256'


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False
    return pwd_context.verify(password, password_hash)


def generate_token(payload: dict, expires_delta: timedelta) -> str:
    to_encode = payload.copy()
    to_encode['exp'] = datetime.now(timezone.utc) + expires_delta
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=ALGORITHM)


def create_access_token(payload: dict) -> str:
    return generate_token(payload, timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))


def create_refresh_token(payload: dict) -> str:
    return generate_token(payload, timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS))


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError as exc:
        raise ValueError('Invalid token') from exc


def token_hash(value: str) -> str:
    return sha256(value.encode()).hexdigest()


def random_secret(length: int = 32) -> str:
    return secrets.token_hex(length // 2)


def random_password(length: int = 14) -> str:
    alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!@#$%*'
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def slugify_name(name: str) -> str:
    return _slugify(name)
''')

add('app/core/exceptions.py', '''
from fastapi import HTTPException


def bad_request(message: str):
    raise HTTPException(status_code=400, detail=message)


def unauthorized(message: str = 'Unauthorized'):
    raise HTTPException(status_code=401, detail=message)


def forbidden(message: str = 'Forbidden'):
    raise HTTPException(status_code=403, detail=message)


def not_found(message: str = 'Not found'):
    raise HTTPException(status_code=404, detail=message)


def conflict(message: str = 'Conflict'):
    raise HTTPException(status_code=409, detail=message)
''')

add('app/db/session.py', '''
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from app.core.config import settings

engine = create_engine(settings.DATABASE_URL, future=True, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
''')

add('app/models/base.py', '''
from app.db.session import Base
from app.models.company import Company
from app.models.user import User
from app.models.role import Role
from app.models.permission import Permission
from app.models.associations import UserRole, RolePermission
from app.models.refresh_session import RefreshSession
from app.models.audit_log import AuditLog
from app.models.login_history import LoginHistory
from app.models.verification_token import VerificationToken
from app.models.api_key import ApiKey
''')

add('app/models/company.py', '''
import uuid
from sqlalchemy import String, Integer, JSON, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class Company(Base):
    __tablename__ = 'companies'

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    domain: Mapped[str | None] = mapped_column(String(150), unique=True)
    status: Mapped[str] = mapped_column(String(20), default='active')
    employee_sequence: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    employee_code_prefix: Mapped[str] = mapped_column(String(20), default='EMP', nullable=False)
    metadata_json: Mapped[dict] = mapped_column('metadata', JSON, default=dict)

    users = relationship('User', back_populates='company')
''')

add('app/models/permission.py', '''
import uuid
from sqlalchemy import String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class Permission(Base):
    __tablename__ = 'permissions'

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    key: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255))

    roles = relationship('Role', secondary='role_permissions', back_populates='permissions')
''')

add('app/models/role.py', '''
import uuid
from sqlalchemy import String, Boolean, ForeignKey, Uuid, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class Role(Base):
    __tablename__ = 'roles'
    __table_args__ = (UniqueConstraint('key', 'company_id', name='roles_key_company_uq'),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255))
    company_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey('companies.id', ondelete='CASCADE'))
    is_system: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    permissions = relationship('Permission', secondary='role_permissions', back_populates='roles')
    users = relationship('User', secondary='user_roles', back_populates='roles')
''')

add('app/models/associations.py', '''
import uuid
from sqlalchemy import ForeignKey, Uuid, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class UserRole(Base):
    __tablename__ = 'user_roles'
    __table_args__ = (UniqueConstraint('user_id', 'role_id', name='user_role_uq'),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    role_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey('roles.id', ondelete='CASCADE'), nullable=False)


class RolePermission(Base):
    __tablename__ = 'role_permissions'
    __table_args__ = (UniqueConstraint('role_id', 'permission_id', name='role_permission_uq'),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    role_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey('roles.id', ondelete='CASCADE'), nullable=False)
    permission_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey('permissions.id', ondelete='CASCADE'), nullable=False)
''')

add('app/models/user.py', '''
import uuid
from datetime import datetime
from sqlalchemy import String, Boolean, DateTime, ForeignKey, JSON, Uuid, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class User(Base):
    __tablename__ = 'users'
    __table_args__ = (
        UniqueConstraint('company_id', 'email', name='users_company_email_uq'),
        UniqueConstraint('company_id', 'employee_code', name='users_company_employee_code_uq'),
        UniqueConstraint('company_id', 'external_employee_id', name='users_company_external_employee_id_uq'),
        UniqueConstraint('company_id', 'payroll_employee_id', name='users_company_payroll_employee_id_uq'),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, index=True)
    keycloak_user_id: Mapped[str | None] = mapped_column(String(64))
    employee_code: Mapped[str | None] = mapped_column(String(80))
    external_employee_id: Mapped[str | None] = mapped_column(String(80))
    payroll_employee_id: Mapped[str | None] = mapped_column(String(80))
    first_name: Mapped[str] = mapped_column(String(80), nullable=False)
    last_name: Mapped[str] = mapped_column(String(80), nullable=False)
    email: Mapped[str] = mapped_column(String(150), nullable=False, index=True)
    password_hash: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(50))
    provider: Mapped[str] = mapped_column(String(20), default='local', nullable=False)
    status: Mapped[str] = mapped_column(String(20), default='active', nullable=False)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    mfa_secret: Mapped[str | None] = mapped_column(String(255))
    login_attempts: Mapped[int] = mapped_column(default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[dict] = mapped_column('metadata', JSON, default=dict)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    company = relationship('Company', back_populates='users')
    roles = relationship('Role', secondary='user_roles', back_populates='users')
''')

add('app/models/refresh_session.py', '''
import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, ForeignKey, JSON, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class RefreshSession(Base):
    __tablename__ = 'refresh_sessions'

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    device_info: Mapped[dict] = mapped_column(JSON, default=dict)
    ip_address: Mapped[str | None] = mapped_column(String(100))
    user_agent: Mapped[str | None] = mapped_column(String(500))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
''')

add('app/models/audit_log.py', '''
import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, JSON, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class AuditLog(Base):
    __tablename__ = 'audit_logs'

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    action: Mapped[str] = mapped_column(String(120), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(100))
    ip_address: Mapped[str | None] = mapped_column(String(100))
    user_agent: Mapped[str | None] = mapped_column(String(500))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
''')

add('app/models/login_history.py', '''
import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class LoginHistory(Base):
    __tablename__ = 'login_history'

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    email: Mapped[str] = mapped_column(String(150), nullable=False)
    company_slug: Mapped[str | None] = mapped_column(String(100))
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(100))
    user_agent: Mapped[str | None] = mapped_column(String(500))
    failure_reason: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
''')

add('app/models/verification_token.py', '''
import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, JSON, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class VerificationToken(Base):
    __tablename__ = 'verification_tokens'

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[dict] = mapped_column('metadata', JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
''')

add('app/models/api_key.py', '''
import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, JSON, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class ApiKey(Base):
    __tablename__ = 'api_keys'

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    prefix: Mapped[str] = mapped_column(String(20), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scopes: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
''')

add('app/api/api.py', '''
from fastapi import APIRouter
from app.api.routes import health, auth, employees, admin, kiosk

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(admin.router)
api_router.include_router(employees.router)
api_router.include_router(kiosk.router)
''')

add('app/middleware/tenant.py', '''
from starlette.middleware.base import BaseHTTPMiddleware
from app.db.session import SessionLocal
from app.models.company import Company


def strip_port(host: str | None) -> str | None:
    return host.split(':')[0].lower() if host else None


class TenantMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        candidates = []
        for key in ['host', 'x-forwarded-host']:
            value = strip_port(request.headers.get(key))
            if value and value not in candidates:
                candidates.append(value)
        for cookie_key in ['tenant_host']:
            value = strip_port(request.cookies.get(cookie_key))
            if value and value not in candidates:
                candidates.append(value)

        db = SessionLocal()
        try:
            tenant = None
            for host in candidates:
                if host in {'localhost', '127.0.0.1'}:
                    continue
                tenant = db.query(Company).filter(Company.domain == host, Company.status == 'active').first()
                if tenant:
                    break
                parts = host.split('.')
                if len(parts) >= 3:
                    slug = parts[0]
                    tenant = db.query(Company).filter(Company.slug == slug, Company.status == 'active').first()
                    if tenant:
                        break
            request.state.tenant = tenant
        finally:
            db.close()
        return await call_next(request)
''')

add('app/schemas/common.py', '''
from pydantic import BaseModel
from typing import Any


class Envelope(BaseModel):
    message: str
    data: Any | None = None
''')

add('app/schemas/auth.py', '''
from uuid import UUID
from pydantic import BaseModel, EmailStr, Field


class BootstrapCompanyRequest(BaseModel):
    company_name: str = Field(min_length=2, max_length=150)
    owner_first_name: str = Field(max_length=80)
    owner_last_name: str = Field(max_length=80)
    owner_email: EmailStr
    owner_password: str = Field(min_length=8, max_length=64)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    mfa_token: str | None = None


class RefreshRequest(BaseModel):
    refresh_token: str | None = None


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    password: str = Field(min_length=8, max_length=64)


class VerifyTokenRequest(BaseModel):
    token: str


class MfaVerifyRequest(BaseModel):
    token: str = Field(min_length=6, max_length=6)


class RevokeSessionRequest(BaseModel):
    session_id: UUID


class CreateApiKeyRequest(BaseModel):
    name: str
    scopes: list[str] = []


class RevokeApiKeyRequest(BaseModel):
    api_key_id: UUID


class ImpersonateRequest(BaseModel):
    target_user_id: UUID


class KioskPinRequest(BaseModel):
    user_id: UUID
    pin: str = Field(pattern=r'^\d{4,6}$')


class KioskLoginRequest(BaseModel):
    employee_code: str
    pin: str = Field(pattern=r'^\d{4,6}$')
''')

add('app/schemas/employee.py', '''
from uuid import UUID
from pydantic import BaseModel, EmailStr, Field


class EmployeeCreateRequest(BaseModel):
    employee_code: str | None = None
    external_employee_id: str | None = None
    payroll_employee_id: str | None = None
    first_name: str
    last_name: str
    email: EmailStr
    phone: str | None = None
    password: str | None = Field(default=None, min_length=8, max_length=64)
    role_key: str = 'employee'
    provider: str = 'local'


class BulkEmployeeCreateRequest(BaseModel):
    users: list[EmployeeCreateRequest]


class RoleCreateRequest(BaseModel):
    key: str
    name: str
    description: str | None = None
    permission_keys: list[str] = []


class IdPath(BaseModel):
    user_id: UUID
''')

add('app/deps/auth.py', '''
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session, selectinload
from sqlalchemy import select

from app.core.security import decode_token
from app.db.session import get_db
from app.models.user import User
from app.models.company import Company
from app.models.role import Role

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme), db: Session = Depends(get_db)):
    token = None
    if credentials:
        token = credentials.credentials
    else:
        token = request.cookies.get('attendio_session') or request.cookies.get('SESSION_COOKIE_NAME')
    if not token:
        raise HTTPException(status_code=401, detail='Authentication required')
    try:
        payload = decode_token(token)
    except ValueError:
        raise HTTPException(status_code=401, detail='Invalid token')

    stmt = (
        select(User)
        .options(selectinload(User.roles).selectinload(Role.permissions), selectinload(User.company))
        .where(User.id == payload.get('sub'))
    )
    user = db.execute(stmt).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail='User not found')
    tenant = getattr(request.state, 'tenant', None)
    if tenant and str(user.company_id) != str(tenant.id):
        raise HTTPException(status_code=403, detail='Cross tenant access denied')
    return user


def require_permissions(*required: str):
    def dependency(user=Depends(get_current_user)):
        permissions = {perm.key for role in user.roles for perm in role.permissions}
        if not any(item in permissions for item in required):
            raise HTTPException(status_code=403, detail='Insufficient permissions')
        return user
    return dependency
''')

add('app/services/audit.py', '''
from sqlalchemy.orm import Session
from app.models.audit_log import AuditLog


def log_audit(db: Session, *, company_id, actor_user_id, action, entity_type, entity_id=None, ip_address=None, user_agent=None, payload=None):
    entry = AuditLog(
        company_id=company_id,
        actor_user_id=actor_user_id,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id else None,
        ip_address=ip_address,
        user_agent=user_agent,
        payload=payload or {},
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry
''')

add('app/services/mfa.py', '''
import pyotp
from sqlalchemy.orm import Session
from app.models.user import User
from app.core.exceptions import bad_request


def generate_setup(db: Session, user: User):
    secret = pyotp.random_base32()
    user.mfa_secret = secret
    db.add(user)
    db.commit()
    provisioning_uri = pyotp.TOTP(secret).provisioning_uri(name=user.email, issuer_name='Attendio')
    return {'secret': secret, 'provisioning_uri': provisioning_uri}


def verify_setup(db: Session, user: User, token: str):
    if not user.mfa_secret:
        bad_request('MFA setup not started')
    ok = pyotp.TOTP(user.mfa_secret).verify(token, valid_window=1)
    if not ok:
        bad_request('Invalid MFA token')
    user.mfa_enabled = True
    db.add(user)
    db.commit()
    return True


def verify_login(user: User, token: str):
    if not user.mfa_secret:
        bad_request('MFA not configured')
    ok = pyotp.TOTP(user.mfa_secret).verify(token, valid_window=1)
    if not ok:
        bad_request('Invalid MFA token')
''')

add('app/services/auth.py', '''
from datetime import datetime, timedelta, timezone
import io
import uuid
import pandas as pd
from sqlalchemy import select, or_
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.core.exceptions import bad_request, conflict, not_found, unauthorized, forbidden
from app.core.security import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    decode_token,
    token_hash,
    random_password,
    random_secret,
    slugify_name,
)
from app.models.company import Company
from app.models.user import User
from app.models.role import Role
from app.models.permission import Permission
from app.models.refresh_session import RefreshSession
from app.models.verification_token import VerificationToken
from app.models.login_history import LoginHistory
from app.models.api_key import ApiKey
from app.services.audit import log_audit
from app.services import mfa as mfa_service


class AuthService:
    def format_employee_code(self, prefix: str, sequence: int) -> str:
        return f'{prefix}-{sequence:06d}'

    def build_tenant_base_url(self, company: Company) -> str:
        return f'http://{company.domain or f"{company.slug}.{settings.DEFAULT_ROOT_DOMAIN}"}'

    def issue_payload(self, user: User, company: Company) -> dict:
        roles = [role.key for role in user.roles]
        permissions = sorted({perm.key for role in user.roles for perm in role.permissions})
        return {
            'sub': str(user.id),
            'email': user.email,
            'company_id': str(company.id),
            'company_slug': company.slug,
            'roles': roles,
            'permissions': permissions,
        }

    def allocate_employee_code(self, db: Session, company: Company) -> str:
        company.employee_sequence += 1
        db.add(company)
        db.flush()
        return self.format_employee_code(company.employee_code_prefix, company.employee_sequence)

    def resolve_company_for_login(self, db: Session, *, email: str, tenant: Company | None) -> Company:
        if tenant:
            return tenant
        stmt = select(User).options(selectinload(User.company)).where(User.email == email.lower())
        matches = db.execute(stmt).scalars().all()
        active_matches = [user.company for user in matches if user.company and user.company.status == 'active']
        unique_ids = {str(company.id): company for company in active_matches}
        if not unique_ids:
            unauthorized('Invalid credentials')
        if len(unique_ids) > 1:
            conflict('Multiple companies found for this email. Please login from your tenant domain.')
        return next(iter(unique_ids.values()))

    def bootstrap_company(self, db: Session, payload, request_meta: dict):
        base_slug = slugify_name(payload.company_name)
        slug = base_slug
        counter = 1
        while db.scalar(select(Company).where(Company.slug == slug)):
            counter += 1
            slug = f'{base_slug}-{counter}'
        domain = f'{slug}.{settings.DEFAULT_ROOT_DOMAIN}'
        owner_email = payload.owner_email.lower()
        company = Company(name=payload.company_name, slug=slug, domain=domain, employee_sequence=0, employee_code_prefix='EMP')
        db.add(company)
        db.flush()
        owner_code = self.allocate_employee_code(db, company)
        owner = User(
            company_id=company.id,
            employee_code=owner_code,
            first_name=payload.owner_first_name,
            last_name=payload.owner_last_name,
            email=owner_email,
            password_hash=hash_password(payload.owner_password),
            provider='local',
            status='active',
            email_verified=False,
        )
        owner_role = db.scalar(select(Role).where(Role.key == 'company_owner', Role.company_id.is_(None)))
        if not owner_role:
            raise RuntimeError('Seed roles missing')
        owner.roles.append(owner_role)
        db.add(owner)
        db.commit()
        db.refresh(company)
        db.refresh(owner)
        log_audit(db, company_id=company.id, actor_user_id=owner.id, action='company.bootstrap', entity_type='company', entity_id=company.id, ip_address=request_meta.get('ip_address'), user_agent=request_meta.get('user_agent'), payload={'slug': company.slug, 'domain': company.domain, 'owner_email': owner.email})
        return company, owner

    def load_user_for_session(self, db: Session, *, user_id: uuid.UUID | str):
        stmt = (
            select(User)
            .options(selectinload(User.roles).selectinload(Role.permissions), selectinload(User.company))
            .where(User.id == user_id)
        )
        return db.execute(stmt).scalar_one_or_none()

    def login(self, db: Session, *, email: str, password: str, mfa_token: str | None, tenant: Company | None, request_meta: dict):
        company = self.resolve_company_for_login(db, email=email, tenant=tenant)
        stmt = (
            select(User)
            .options(selectinload(User.roles).selectinload(Role.permissions), selectinload(User.company))
            .where(User.company_id == company.id, User.email == email.lower())
        )
        user = db.execute(stmt).scalar_one_or_none()
        if not user or not verify_password(password, user.password_hash):
            if user:
                user.login_attempts += 1
                if user.login_attempts >= settings.LOGIN_MAX_ATTEMPTS:
                    user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=settings.LOGIN_LOCK_MINUTES)
                    user.status = 'locked'
                db.add(user)
                db.commit()
            entry = LoginHistory(user_id=user.id if user else None, email=email.lower(), company_slug=company.slug, provider='local', status='failed', ip_address=request_meta.get('ip_address'), user_agent=request_meta.get('user_agent'), failure_reason='invalid_password')
            db.add(entry)
            db.commit()
            unauthorized('Invalid credentials')
        if user.locked_until and user.locked_until > datetime.now(timezone.utc):
            unauthorized('Account temporarily locked')
        if user.mfa_enabled:
            if not mfa_token:
                unauthorized('MFA token is required')
            mfa_service.verify_login(user, mfa_token)
        user.login_attempts = 0
        user.locked_until = None
        user.status = 'active'
        user.last_login_at = datetime.now(timezone.utc)
        db.add(user)
        payload = self.issue_payload(user, company)
        access_token = create_access_token(payload)
        refresh_token = create_refresh_token(payload)
        session = RefreshSession(user_id=user.id, token_hash=token_hash(refresh_token), expires_at=datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS), last_used_at=datetime.now(timezone.utc), ip_address=request_meta.get('ip_address'), user_agent=request_meta.get('user_agent'), device_info={'user_agent': request_meta.get('user_agent')})
        db.add(session)
        db.add(LoginHistory(user_id=user.id, email=user.email, company_slug=company.slug, provider='local', status='success', ip_address=request_meta.get('ip_address'), user_agent=request_meta.get('user_agent')))
        db.commit()
        log_audit(db, company_id=company.id, actor_user_id=user.id, action='auth.login', entity_type='session', entity_id=user.id, ip_address=request_meta.get('ip_address'), user_agent=request_meta.get('user_agent'), payload={'provider': 'local'})
        return {
            'user': user,
            'company': company,
            'access_token': access_token,
            'refresh_token': refresh_token,
            'tenant_base_url': self.build_tenant_base_url(company),
            'redirect_url': f'{self.build_tenant_base_url(company)}{settings.FRONTEND_AFTER_LOGIN}',
            'display_message': f'Login successful. Welcome, {user.first_name} {user.last_name}',
        }

    def refresh(self, db: Session, *, refresh_token: str):
        payload = decode_token(refresh_token)
        session = db.scalar(select(RefreshSession).where(RefreshSession.token_hash == token_hash(refresh_token), RefreshSession.revoked_at.is_(None)))
        if not session:
            unauthorized('Refresh session not found')
        user = self.load_user_for_session(db, user_id=payload['sub'])
        if not user:
            unauthorized('User not found')
        session.last_used_at = datetime.now(timezone.utc)
        db.add(session)
        db.commit()
        new_payload = self.issue_payload(user, user.company)
        return {'access_token': create_access_token(new_payload), 'refresh_token': create_refresh_token(new_payload), 'company': user.company}

    def logout(self, db: Session, refresh_token: str | None):
        if not refresh_token:
            return
        session = db.scalar(select(RefreshSession).where(RefreshSession.token_hash == token_hash(refresh_token), RefreshSession.revoked_at.is_(None)))
        if session:
            session.revoked_at = datetime.now(timezone.utc)
            db.add(session)
            db.commit()

    def register_employee(self, db: Session, *, actor: User, payload, request_meta: dict):
        role = db.scalar(select(Role).where(Role.key == payload.role_key).where(or_(Role.company_id.is_(None), Role.company_id == actor.company_id)))
        if not role:
            bad_request('Invalid role')
        email = payload.email.lower()
        existing_filters = [User.email == email]
        if payload.employee_code:
            existing_filters.append(User.employee_code == payload.employee_code)
        if payload.external_employee_id:
            existing_filters.append(User.external_employee_id == payload.external_employee_id)
        if payload.payroll_employee_id:
            existing_filters.append(User.payroll_employee_id == payload.payroll_employee_id)
        existing = db.scalar(select(User).where(User.company_id == actor.company_id).where(or_(*existing_filters)))
        if existing:
            conflict('User, email, or employee identifier already exists in this company')
        company = actor.company
        employee_code = payload.employee_code or self.allocate_employee_code(db, company)
        generated_password = payload.password or (random_password() if payload.provider == 'local' else None)
        user = User(
            company_id=actor.company_id,
            employee_code=employee_code,
            external_employee_id=payload.external_employee_id,
            payroll_employee_id=payload.payroll_employee_id,
            first_name=payload.first_name,
            last_name=payload.last_name,
            email=email,
            phone=payload.phone,
            password_hash=hash_password(generated_password) if generated_password else None,
            provider=payload.provider,
            status='active' if generated_password else 'invited',
            email_verified=False,
        )
        user.roles.append(role)
        db.add(user)
        db.commit()
        db.refresh(user)
        log_audit(db, company_id=actor.company_id, actor_user_id=actor.id, action='user.registered', entity_type='user', entity_id=user.id, ip_address=request_meta.get('ip_address'), user_agent=request_meta.get('user_agent'), payload={'email': user.email, 'employee_code': user.employee_code, 'role': role.key})
        return user, (None if payload.password else generated_password)

    def import_employees(self, db: Session, *, actor: User, filename: str, raw_bytes: bytes, request_meta: dict):
        ext = filename.rsplit('.', 1)[-1].lower()
        if ext == 'csv':
            frame = pd.read_csv(io.BytesIO(raw_bytes))
        elif ext in {'xlsx', 'xls'}:
            frame = pd.read_excel(io.BytesIO(raw_bytes))
        else:
            bad_request('Only csv, xlsx, and xls files are supported')
        results = []
        for row in frame.fillna('').to_dict(orient='records'):
            class Payload: ...
            payload = Payload()
            payload.employee_code = row.get('employee_code') or row.get('employeeCode') or None
            payload.external_employee_id = row.get('external_employee_id') or row.get('externalEmployeeId') or None
            payload.payroll_employee_id = row.get('payroll_employee_id') or row.get('payrollEmployeeId') or None
            payload.first_name = row.get('first_name') or row.get('firstName')
            payload.last_name = row.get('last_name') or row.get('lastName')
            payload.email = row.get('email')
            payload.phone = row.get('phone') or None
            payload.password = row.get('password') or None
            payload.role_key = row.get('role_key') or row.get('roleKey') or 'employee'
            payload.provider = row.get('provider') or 'local'
            try:
                user, generated_password = self.register_employee(db, actor=actor, payload=payload, request_meta=request_meta)
                results.append({'email': user.email, 'status': 'created', 'user_id': str(user.id), 'employee_code': user.employee_code, 'generated_password': generated_password})
            except Exception as exc:
                db.rollback()
                results.append({'email': payload.email, 'status': 'failed', 'reason': str(exc)})
        return results

    def issue_verification_token(self, db: Session, *, user: User, token_type: str):
        raw = random_secret(32)
        expires = datetime.now(timezone.utc) + (timedelta(minutes=settings.PASSWORD_RESET_EXPIRE_MINUTES) if token_type == 'password_reset' else timedelta(hours=settings.EMAIL_VERIFICATION_EXPIRE_HOURS))
        item = VerificationToken(user_id=user.id, company_id=user.company_id, type=token_type, token_hash=token_hash(raw), expires_at=expires, metadata_json={'email': user.email})
        db.add(item)
        db.commit()
        return raw

    def request_email_verification(self, db: Session, *, actor: User, request_meta: dict):
        token = self.issue_verification_token(db, user=actor, token_type='email_verification')
        log_audit(db, company_id=actor.company_id, actor_user_id=actor.id, action='auth.email_verification_requested', entity_type='user', entity_id=actor.id, ip_address=request_meta.get('ip_address'), user_agent=request_meta.get('user_agent'), payload={'delivered': False})
        return {'token': token}

    def verify_email(self, db: Session, *, token: str, request_meta: dict):
        record = db.scalar(select(VerificationToken).where(VerificationToken.token_hash == token_hash(token), VerificationToken.type == 'email_verification', VerificationToken.consumed_at.is_(None)))
        if not record or record.expires_at < datetime.now(timezone.utc):
            bad_request('Invalid or expired verification token')
        user = db.scalar(select(User).where(User.id == record.user_id))
        record.consumed_at = datetime.now(timezone.utc)
        user.email_verified = True
        db.add(record)
        db.add(user)
        db.commit()
        log_audit(db, company_id=user.company_id, actor_user_id=user.id, action='auth.email_verified', entity_type='user', entity_id=user.id, ip_address=request_meta.get('ip_address'), user_agent=request_meta.get('user_agent'), payload={})

    def forgot_password(self, db: Session, *, email: str, request_meta: dict):
        user = db.scalar(select(User).where(User.email == email.lower()))
        if not user:
            return {'sent': True}
        token = self.issue_verification_token(db, user=user, token_type='password_reset')
        log_audit(db, company_id=user.company_id, actor_user_id=user.id, action='auth.password_reset_requested', entity_type='user', entity_id=user.id, ip_address=request_meta.get('ip_address'), user_agent=request_meta.get('user_agent'), payload={'delivered': False})
        return {'sent': True, 'token': token}

    def reset_password(self, db: Session, *, token: str, password: str, request_meta: dict):
        record = db.scalar(select(VerificationToken).where(VerificationToken.token_hash == token_hash(token), VerificationToken.type == 'password_reset', VerificationToken.consumed_at.is_(None)))
        if not record or record.expires_at < datetime.now(timezone.utc):
            bad_request('Invalid or expired reset token')
        user = db.scalar(select(User).where(User.id == record.user_id))
        record.consumed_at = datetime.now(timezone.utc)
        user.password_hash = hash_password(password)
        user.status = 'active'
        user.login_attempts = 0
        user.locked_until = None
        db.add(record)
        db.add(user)
        db.commit()
        log_audit(db, company_id=user.company_id, actor_user_id=user.id, action='auth.password_reset_completed', entity_type='user', entity_id=user.id, ip_address=request_meta.get('ip_address'), user_agent=request_meta.get('user_agent'), payload={})

    def list_sessions(self, db: Session, *, actor: User):
        return db.execute(select(RefreshSession).where(RefreshSession.user_id == actor.id).order_by(RefreshSession.created_at.desc())).scalars().all()

    def revoke_session(self, db: Session, *, actor: User, session_id: uuid.UUID):
        session = db.scalar(select(RefreshSession).where(RefreshSession.id == session_id, RefreshSession.user_id == actor.id, RefreshSession.revoked_at.is_(None)))
        if not session:
            not_found('Session not found')
        session.revoked_at = datetime.now(timezone.utc)
        db.add(session)
        db.commit()

    def revoke_all_sessions(self, db: Session, *, actor: User):
        sessions = db.execute(select(RefreshSession).where(RefreshSession.user_id == actor.id, RefreshSession.revoked_at.is_(None))).scalars().all()
        for session in sessions:
            session.revoked_at = datetime.now(timezone.utc)
            db.add(session)
        db.commit()

    def create_api_key(self, db: Session, *, actor: User, name: str, scopes: list[str], request_meta: dict):
        secret = random_secret(32)
        value = f'ak_{secret}'
        record = ApiKey(company_id=actor.company_id, created_by_user_id=actor.id, name=name, scopes=scopes, prefix=value[:12], key_hash=token_hash(value))
        db.add(record)
        db.commit()
        db.refresh(record)
        log_audit(db, company_id=actor.company_id, actor_user_id=actor.id, action='api_key.created', entity_type='api_key', entity_id=record.id, ip_address=request_meta.get('ip_address'), user_agent=request_meta.get('user_agent'), payload={'name': name, 'scopes': scopes})
        return value, record

    def list_api_keys(self, db: Session, *, actor: User):
        return db.execute(select(ApiKey).where(ApiKey.company_id == actor.company_id).order_by(ApiKey.created_at.desc())).scalars().all()

    def revoke_api_key(self, db: Session, *, actor: User, api_key_id: uuid.UUID, request_meta: dict):
        record = db.scalar(select(ApiKey).where(ApiKey.id == api_key_id, ApiKey.company_id == actor.company_id, ApiKey.revoked_at.is_(None)))
        if not record:
            not_found('API key not found')
        record.revoked_at = datetime.now(timezone.utc)
        db.add(record)
        db.commit()
        log_audit(db, company_id=actor.company_id, actor_user_id=actor.id, action='api_key.revoked', entity_type='api_key', entity_id=record.id, ip_address=request_meta.get('ip_address'), user_agent=request_meta.get('user_agent'), payload={})

    def impersonate(self, db: Session, *, actor: User, target_user_id: uuid.UUID, request_meta: dict):
        perms = {perm.key for role in actor.roles for perm in role.permissions}
        if 'users.impersonate' not in perms and 'settings.tenant' not in perms:
            forbidden('Insufficient permissions')
        target = self.load_user_for_session(db, user_id=target_user_id)
        if not target or target.company_id != actor.company_id:
            not_found('Target user not found')
        payload = self.issue_payload(target, target.company)
        payload['impersonated_by'] = str(actor.id)
        access = create_access_token(payload)
        refresh = create_refresh_token(payload)
        db.add(RefreshSession(user_id=target.id, token_hash=token_hash(refresh), expires_at=datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS), last_used_at=datetime.now(timezone.utc), ip_address=request_meta.get('ip_address'), user_agent=request_meta.get('user_agent'), device_info={'user_agent': request_meta.get('user_agent')}))
        db.commit()
        log_audit(db, company_id=actor.company_id, actor_user_id=actor.id, action='auth.impersonation_started', entity_type='user', entity_id=target.id, ip_address=request_meta.get('ip_address'), user_agent=request_meta.get('user_agent'), payload={'target_email': target.email})
        return {'target': target, 'company': target.company, 'access_token': access, 'refresh_token': refresh}

    def set_kiosk_pin(self, db: Session, *, actor: User, target_user_id: uuid.UUID, pin: str, request_meta: dict):
        target = db.scalar(select(User).where(User.id == target_user_id, User.company_id == actor.company_id))
        if not target:
            not_found('Target user not found')
        metadata = target.metadata_json or {}
        metadata['kiosk_pin_hash'] = token_hash(pin)
        metadata['kiosk_pin_updated_at'] = datetime.now(timezone.utc).isoformat()
        target.metadata_json = metadata
        db.add(target)
        db.commit()
        log_audit(db, company_id=actor.company_id, actor_user_id=actor.id, action='kiosk.pin_set', entity_type='user', entity_id=target.id, ip_address=request_meta.get('ip_address'), user_agent=request_meta.get('user_agent'), payload={})

    def kiosk_login(self, db: Session, *, actor_tenant: Company | None, employee_code: str, pin: str, request_meta: dict):
        if not actor_tenant:
            bad_request('Kiosk login requires tenant domain resolution')
        user = self.load_user_for_session(db, user_id=(db.scalar(select(User.id).where(User.company_id == actor_tenant.id, User.employee_code == employee_code))))
        if not user:
            unauthorized('Invalid kiosk credentials')
        pin_hash = (user.metadata_json or {}).get('kiosk_pin_hash')
        if not pin_hash or pin_hash != token_hash(pin):
            unauthorized('Invalid kiosk credentials')
        payload = self.issue_payload(user, actor_tenant)
        payload['kiosk'] = True
        access = create_access_token(payload)
        refresh = create_refresh_token(payload)
        db.add(RefreshSession(user_id=user.id, token_hash=token_hash(refresh), expires_at=datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS), last_used_at=datetime.now(timezone.utc), ip_address=request_meta.get('ip_address'), user_agent=request_meta.get('user_agent'), device_info={'user_agent': request_meta.get('user_agent')}))
        db.commit()
        log_audit(db, company_id=actor_tenant.id, actor_user_id=user.id, action='kiosk.login', entity_type='session', entity_id=user.id, ip_address=request_meta.get('ip_address'), user_agent=request_meta.get('user_agent'), payload={'employee_code': employee_code})
        return {'user': user, 'company': actor_tenant, 'access_token': access, 'refresh_token': refresh, 'redirect_url': f'{self.build_tenant_base_url(actor_tenant)}/kiosk'}

    def list_permissions(self, db: Session):
        return db.execute(select(Permission).order_by(Permission.key.asc())).scalars().all()

    def list_roles(self, db: Session, *, actor: User):
        return db.execute(select(Role).options(selectinload(Role.permissions)).where(or_(Role.company_id.is_(None), Role.company_id == actor.company_id)).order_by(Role.key.asc())).scalars().all()

    def create_role(self, db: Session, *, actor: User, key: str, name: str, description: str | None, permission_keys: list[str], request_meta: dict):
        existing = db.scalar(select(Role).where(Role.key == key, Role.company_id == actor.company_id))
        if existing:
            conflict('Role key already exists for this company')
        perms = db.execute(select(Permission).where(Permission.key.in_(permission_keys))).scalars().all() if permission_keys else []
        role = Role(key=key, name=name, description=description, company_id=actor.company_id, is_system=False)
        role.permissions = perms
        db.add(role)
        db.commit()
        db.refresh(role)
        log_audit(db, company_id=actor.company_id, actor_user_id=actor.id, action='role.created', entity_type='role', entity_id=role.id, ip_address=request_meta.get('ip_address'), user_agent=request_meta.get('user_agent'), payload={'key': key, 'permission_keys': permission_keys})
        return role

    def list_employees(self, db: Session, *, actor: User):
        stmt = select(User).options(selectinload(User.roles).selectinload(Role.permissions)).where(User.company_id == actor.company_id).order_by(User.created_at.desc())
        return db.execute(stmt).scalars().all()

    def get_employee(self, db: Session, *, actor: User, user_id: uuid.UUID):
        stmt = select(User).options(selectinload(User.roles).selectinload(Role.permissions)).where(User.company_id == actor.company_id, User.id == user_id)
        user = db.execute(stmt).scalar_one_or_none()
        if not user:
            not_found('Employee not found')
        return user

    def list_audit_logs(self, db: Session, *, actor: User):
        from app.models.audit_log import AuditLog
        return db.execute(select(AuditLog).where(AuditLog.company_id == actor.company_id).order_by(AuditLog.created_at.desc()).limit(200)).scalars().all()

service = AuthService()
''')

add('app/services/sso.py', '''
from fastapi import HTTPException
from authlib.integrations.starlette_client import OAuth
from app.core.config import settings


oauth = OAuth()


def get_provider_config(provider: str):
    if provider == 'google':
        if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
            raise HTTPException(status_code=501, detail='Google SSO is not configured')
        return {
            'client_id': settings.GOOGLE_CLIENT_ID,
            'client_secret': settings.GOOGLE_CLIENT_SECRET,
            'server_metadata_url': 'https://accounts.google.com/.well-known/openid-configuration',
            'client_kwargs': {'scope': 'openid email profile'},
        }
    if provider == 'microsoft':
        if not settings.MICROSOFT_CLIENT_ID or not settings.MICROSOFT_CLIENT_SECRET:
            raise HTTPException(status_code=501, detail='Microsoft SSO is not configured')
        return {
            'client_id': settings.MICROSOFT_CLIENT_ID,
            'client_secret': settings.MICROSOFT_CLIENT_SECRET,
            'server_metadata_url': 'https://login.microsoftonline.com/common/v2.0/.well-known/openid-configuration',
            'client_kwargs': {'scope': 'openid email profile User.Read'},
        }
    raise HTTPException(status_code=400, detail='Unsupported SSO provider')
''')

add('app/api/routes/health.py', '''
from fastapi import APIRouter

router = APIRouter(tags=['Health'])


@router.get('/health')
def health():
    return {'message': 'Service healthy', 'data': {'status': 'ok'}}
''')

add('app/api/routes/auth.py', '''
from fastapi import APIRouter, Depends, Request, Response, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.deps.auth import get_current_user, require_permissions
from app.schemas.auth import (
    BootstrapCompanyRequest,
    LoginRequest,
    RefreshRequest,
    ForgotPasswordRequest,
    ResetPasswordRequest,
    VerifyTokenRequest,
    MfaVerifyRequest,
    RevokeSessionRequest,
    CreateApiKeyRequest,
    RevokeApiKeyRequest,
    ImpersonateRequest,
)
from app.services.auth import service
from app.services import mfa as mfa_service
from app.services.sso import get_provider_config
from authlib.integrations.starlette_client import OAuth

router = APIRouter(prefix='/auth')
oauth = OAuth()


def req_meta(request: Request):
    return {'ip_address': request.client.host if request.client else None, 'user_agent': request.headers.get('user-agent')}


def set_auth_cookies(response: Response, access_token: str, refresh_token: str, company):
    opts = {'httponly': True, 'samesite': 'lax', 'secure': settings.COOKIE_SECURE, 'path': '/'}
    if settings.COOKIE_DOMAIN:
        opts['domain'] = settings.COOKIE_DOMAIN
    response.set_cookie(settings.SESSION_COOKIE_NAME, access_token, max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60, **opts)
    response.set_cookie(settings.REFRESH_COOKIE_NAME, refresh_token, max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600, **opts)
    response.set_cookie('tenant_slug', company.slug, max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600, **opts)
    response.set_cookie('tenant_host', company.domain, max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600, **opts)


@router.post('/bootstrap-company', tags=['Authentication'])
def bootstrap_company(payload: BootstrapCompanyRequest, request: Request, db: Session = Depends(get_db)):
    company, user = service.bootstrap_company(db, payload, req_meta(request))
    return {
        'message': 'Company bootstrapped successfully',
        'data': {
            'company': {'id': str(company.id), 'name': company.name, 'slug': company.slug, 'domain': company.domain},
            'user': {'id': str(user.id), 'email': user.email, 'first_name': user.first_name, 'last_name': user.last_name, 'employee_code': user.employee_code},
            'notes': {
                'slug_is_auto_generated': True,
                'domain_is_auto_generated': True,
                'tenant_login_url': service.build_tenant_base_url(company),
            },
        },
    }


@router.post('/login', tags=['Authentication'])
def login(payload: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    tenant = getattr(request.state, 'tenant', None)
    data = service.login(db, email=payload.email, password=payload.password, mfa_token=payload.mfa_token, tenant=tenant, request_meta=req_meta(request))
    set_auth_cookies(response, data['access_token'], data['refresh_token'], data['company'])
    return {
        'message': data['display_message'],
        'data': {
            'access_token': data['access_token'],
            'refresh_token': data['refresh_token'],
            'display_name': f"{data['user'].first_name} {data['user'].last_name}",
            'user': {'id': str(data['user'].id), 'email': data['user'].email, 'first_name': data['user'].first_name, 'last_name': data['user'].last_name, 'employee_code': data['user'].employee_code},
            'company': {'id': str(data['company'].id), 'name': data['company'].name, 'slug': data['company'].slug, 'domain': data['company'].domain},
            'tenant_base_url': data['tenant_base_url'],
            'redirect_url': data['redirect_url'],
            'tenant_isolation': 'enabled',
        },
    }


@router.post('/refresh', tags=['Authentication'])
def refresh(payload: RefreshRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    incoming = payload.refresh_token or request.cookies.get(settings.REFRESH_COOKIE_NAME)
    if not incoming:
        raise HTTPException(status_code=401, detail='Refresh token is required')
    data = service.refresh(db, refresh_token=incoming)
    set_auth_cookies(response, data['access_token'], data['refresh_token'], data['company'])
    return {'message': 'Session refreshed', 'data': data}


@router.post('/logout', tags=['Authentication'])
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    token = request.cookies.get(settings.REFRESH_COOKIE_NAME)
    service.logout(db, token)
    for name in [settings.SESSION_COOKIE_NAME, settings.REFRESH_COOKIE_NAME, 'tenant_slug', 'tenant_host']:
        response.delete_cookie(name, path='/')
    return {'message': 'Logged out successfully'}


@router.get('/me', tags=['Authentication'])
def me(user=Depends(get_current_user)):
    permissions = sorted({perm.key for role in user.roles for perm in role.permissions})
    return {'message': 'Current user fetched successfully', 'data': {'user': {'id': str(user.id), 'first_name': user.first_name, 'last_name': user.last_name, 'email': user.email}, 'company': {'id': str(user.company.id), 'name': user.company.name, 'slug': user.company.slug, 'domain': user.company.domain}, 'permissions': permissions}}


@router.post('/forgot-password', tags=['Authentication'])
def forgot_password(payload: ForgotPasswordRequest, request: Request, db: Session = Depends(get_db)):
    return {'message': 'Password reset flow triggered', 'data': service.forgot_password(db, email=payload.email, request_meta=req_meta(request))}


@router.post('/reset-password', tags=['Authentication'])
def reset_password(payload: ResetPasswordRequest, request: Request, db: Session = Depends(get_db)):
    service.reset_password(db, token=payload.token, password=payload.password, request_meta=req_meta(request))
    return {'message': 'Password reset successfully'}


@router.post('/email/verification', tags=['Authentication'])
def email_verification(request: Request, db: Session = Depends(get_db), user=Depends(get_current_user)):
    return {'message': 'Email verification issued', 'data': service.request_email_verification(db, actor=user, request_meta=req_meta(request))}


@router.post('/verify-email', tags=['Authentication'])
def verify_email(payload: VerifyTokenRequest, request: Request, db: Session = Depends(get_db)):
    service.verify_email(db, token=payload.token, request_meta=req_meta(request))
    return {'message': 'Email verified successfully'}


@router.post('/mfa/setup', tags=['MFA'])
def mfa_setup(db: Session = Depends(get_db), user=Depends(get_current_user)):
    return {'message': 'MFA setup generated', 'data': mfa_service.generate_setup(db, user)}


@router.post('/mfa/verify', tags=['MFA'])
def mfa_verify(payload: MfaVerifyRequest, db: Session = Depends(get_db), user=Depends(get_current_user)):
    mfa_service.verify_setup(db, user, payload.token)
    return {'message': 'MFA enabled successfully'}


@router.get('/sessions', tags=['Sessions'])
def sessions(db: Session = Depends(get_db), user=Depends(get_current_user)):
    items = service.list_sessions(db, actor=user)
    return {'message': 'Sessions fetched successfully', 'data': [{'id': str(item.id), 'ip_address': item.ip_address, 'user_agent': item.user_agent, 'created_at': item.created_at, 'last_used_at': item.last_used_at, 'revoked_at': item.revoked_at} for item in items]}


@router.post('/sessions/revoke', tags=['Sessions'])
def revoke_session(payload: RevokeSessionRequest, db: Session = Depends(get_db), user=Depends(get_current_user)):
    service.revoke_session(db, actor=user, session_id=payload.session_id)
    return {'message': 'Session revoked successfully'}


@router.post('/sessions/revoke-all', tags=['Sessions'])
def revoke_all_sessions(db: Session = Depends(get_db), user=Depends(get_current_user)):
    service.revoke_all_sessions(db, actor=user)
    return {'message': 'All sessions revoked successfully'}


@router.get('/audit-logs', tags=['Audit Logs'])
def audit_logs(db: Session = Depends(get_db), user=Depends(require_permissions('audit.read', 'reports.company'))):
    items = service.list_audit_logs(db, actor=user)
    return {'message': 'Audit logs fetched successfully', 'data': [{'id': str(item.id), 'action': item.action, 'entity_type': item.entity_type, 'entity_id': item.entity_id, 'payload': item.payload, 'created_at': item.created_at} for item in items]}


@router.get('/api-keys', tags=['API Keys'])
def list_api_keys(db: Session = Depends(get_db), user=Depends(require_permissions('api_keys.manage', 'settings.tenant'))):
    items = service.list_api_keys(db, actor=user)
    return {'message': 'API keys fetched successfully', 'data': [{'id': str(item.id), 'name': item.name, 'prefix': item.prefix, 'scopes': item.scopes, 'created_at': item.created_at, 'revoked_at': item.revoked_at} for item in items]}


@router.post('/api-keys', tags=['API Keys'])
def create_api_key(payload: CreateApiKeyRequest, request: Request, db: Session = Depends(get_db), user=Depends(require_permissions('api_keys.manage', 'settings.tenant'))):
    value, record = service.create_api_key(db, actor=user, name=payload.name, scopes=payload.scopes, request_meta=req_meta(request))
    return {'message': 'API key created successfully', 'data': {'api_key': value, 'record': {'id': str(record.id), 'name': record.name, 'prefix': record.prefix}}}


@router.post('/api-keys/revoke', tags=['API Keys'])
def revoke_api_key(payload: RevokeApiKeyRequest, request: Request, db: Session = Depends(get_db), user=Depends(require_permissions('api_keys.manage', 'settings.tenant'))):
    service.revoke_api_key(db, actor=user, api_key_id=payload.api_key_id, request_meta=req_meta(request))
    return {'message': 'API key revoked successfully'}


@router.post('/impersonate', tags=['Authentication'])
def impersonate(payload: ImpersonateRequest, request: Request, response: Response, db: Session = Depends(get_db), user=Depends(get_current_user)):
    data = service.impersonate(db, actor=user, target_user_id=payload.target_user_id, request_meta=req_meta(request))
    set_auth_cookies(response, data['access_token'], data['refresh_token'], data['company'])
    return {'message': f'Impersonation started. Now acting as {data["target"].first_name} {data["target"].last_name}', 'data': {'access_token': data['access_token'], 'refresh_token': data['refresh_token'], 'target_user': {'id': str(data['target'].id), 'email': data['target'].email}}}


@router.get('/sso/callback', tags=['SSO'])
async def sso_callback(request: Request):
    provider = request.query_params.get('provider') or 'unknown'
    return {'message': 'SSO callback received', 'data': {'provider': provider, 'note': 'Provider callback wiring is ready. Complete your tenant specific user provisioning rules here.'}}


@router.get('/sso/{provider}', tags=['SSO'])
async def start_sso(provider: str, request: Request):
    provider = provider.lower().strip()
    config = get_provider_config(provider)
    client = oauth.register(name=provider, **config)
    redirect_uri = settings.OAUTH_REDIRECT_URI
    return await client.authorize_redirect(request, redirect_uri)
''')

add('app/api/routes/employees.py', '''
from pathlib import Path
from fastapi import APIRouter, Depends, UploadFile, File
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps.auth import require_permissions
from app.schemas.employee import EmployeeCreateRequest, BulkEmployeeCreateRequest
from app.services.auth import service

router = APIRouter(prefix='/employees')


def req_meta(request):
    return {'ip_address': request.client.host if request.client else None, 'user_agent': request.headers.get('user-agent')}


def serialize_user(user, generated_password=None):
    perms = sorted({perm.key for role in user.roles for perm in role.permissions}) if getattr(user, 'roles', None) else []
    return {
        'id': str(user.id),
        'company_id': str(user.company_id),
        'employee_code': user.employee_code,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'email': user.email,
        'provider': user.provider,
        'status': user.status,
        'permissions': perms,
        'generated_password': generated_password,
    }


@router.get('', tags=['Employees'])
def list_employees(db: Session = Depends(get_db), user=Depends(require_permissions('users.invite', 'reports.company'))):
    items = service.list_employees(db, actor=user)
    return {'message': 'Employees fetched successfully', 'data': [serialize_user(item) for item in items]}


@router.get('/{user_id}', tags=['Employees'])
def get_employee(user_id: str, db: Session = Depends(get_db), user=Depends(require_permissions('users.invite', 'reports.company'))):
    item = service.get_employee(db, actor=user, user_id=user_id)
    return {'message': 'Employee fetched successfully', 'data': serialize_user(item)}


@router.post('', tags=['Employees'])
def create_employee(payload: EmployeeCreateRequest, request, db: Session = Depends(get_db), user=Depends(require_permissions('users.invite'))):
    item, generated_password = service.register_employee(db, actor=user, payload=payload, request_meta=req_meta(request))
    return {'message': 'Employee registered successfully', 'data': serialize_user(item, generated_password)}


@router.post('/bulk', tags=['Employees'])
def create_bulk(payload: BulkEmployeeCreateRequest, request, db: Session = Depends(get_db), user=Depends(require_permissions('users.invite'))):
    results = []
    for item in payload.users:
        try:
            created, generated_password = service.register_employee(db, actor=user, payload=item, request_meta=req_meta(request))
            results.append({'email': created.email, 'status': 'created', 'user_id': str(created.id), 'employee_code': created.employee_code, 'generated_password': generated_password})
        except Exception as exc:
            db.rollback()
            results.append({'email': item.email, 'status': 'failed', 'reason': str(exc)})
    return {'message': 'Bulk registration completed', 'data': results}


@router.post('/import', tags=['Employees'])
async def import_employees(request, file: UploadFile = File(...), db: Session = Depends(get_db), user=Depends(require_permissions('users.invite'))):
    raw = await file.read()
    results = service.import_employees(db, actor=user, filename=file.filename, raw_bytes=raw, request_meta=req_meta(request))
    return {'message': 'Employee import completed', 'data': results}


@router.get('/import/template', tags=['Employees'])
def import_template(user=Depends(require_permissions('users.invite'))):
    path = Path(__file__).resolve().parents[3] / 'templates' / 'employee-import-template.csv'
    return FileResponse(path, media_type='text/csv', filename='employee-import-template.csv')
''')

add('app/api/routes/admin.py', '''
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps.auth import require_permissions
from app.schemas.employee import RoleCreateRequest
from app.services.auth import service

router = APIRouter()


def req_meta(request: Request):
    return {'ip_address': request.client.host if request.client else None, 'user_agent': request.headers.get('user-agent')}


@router.get('/permissions', tags=['Roles & Permissions'])
def permissions(db: Session = Depends(get_db), user=Depends(require_permissions('roles.manage', 'settings.tenant'))):
    items = service.list_permissions(db)
    return {'message': 'Permissions fetched successfully', 'data': [{'id': str(item.id), 'key': item.key, 'name': item.name, 'description': item.description} for item in items]}


@router.get('/roles', tags=['Roles & Permissions'])
def roles(db: Session = Depends(get_db), user=Depends(require_permissions('roles.manage', 'settings.tenant'))):
    items = service.list_roles(db, actor=user)
    return {'message': 'Roles fetched successfully', 'data': [{'id': str(item.id), 'key': item.key, 'name': item.name, 'description': item.description, 'company_id': str(item.company_id) if item.company_id else None, 'is_system': item.is_system, 'permissions': [perm.key for perm in item.permissions]} for item in items]}


@router.post('/roles', tags=['Roles & Permissions'])
def create_role(payload: RoleCreateRequest, request: Request, db: Session = Depends(get_db), user=Depends(require_permissions('roles.manage', 'settings.tenant'))):
    item = service.create_role(db, actor=user, key=payload.key, name=payload.name, description=payload.description, permission_keys=payload.permission_keys, request_meta=req_meta(request))
    return {'message': 'Role created successfully', 'data': {'id': str(item.id), 'key': item.key, 'name': item.name}}
''')

add('app/api/routes/kiosk.py', '''
from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps.auth import require_permissions
from app.schemas.auth import KioskPinRequest, KioskLoginRequest
from app.services.auth import service
from app.core.config import settings

router = APIRouter(prefix='/kiosk')


def req_meta(request: Request):
    return {'ip_address': request.client.host if request.client else None, 'user_agent': request.headers.get('user-agent')}


def set_auth_cookies(response: Response, access_token: str, refresh_token: str, company):
    opts = {'httponly': True, 'samesite': 'lax', 'secure': settings.COOKIE_SECURE, 'path': '/'}
    response.set_cookie(settings.SESSION_COOKIE_NAME, access_token, max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60, **opts)
    response.set_cookie(settings.REFRESH_COOKIE_NAME, refresh_token, max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600, **opts)
    response.set_cookie('tenant_slug', company.slug, max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600, **opts)
    response.set_cookie('tenant_host', company.domain, max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600, **opts)


@router.post('/pin', tags=['Kiosk'])
def set_kiosk_pin(payload: KioskPinRequest, request: Request, db: Session = Depends(get_db), user=Depends(require_permissions('users.reset_pin', 'settings.kiosk'))):
    service.set_kiosk_pin(db, actor=user, target_user_id=payload.user_id, pin=payload.pin, request_meta=req_meta(request))
    return {'message': 'Kiosk PIN set successfully'}


@router.post('/login', tags=['Kiosk'])
def kiosk_login(payload: KioskLoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    tenant = getattr(request.state, 'tenant', None)
    data = service.kiosk_login(db, actor_tenant=tenant, employee_code=payload.employee_code, pin=payload.pin, request_meta=req_meta(request))
    set_auth_cookies(response, data['access_token'], data['refresh_token'], data['company'])
    return {'message': f'Kiosk login successful. Welcome, {data["user"].first_name} {data["user"].last_name}', 'data': {'user': {'id': str(data['user'].id), 'employee_code': data['user'].employee_code}, 'redirect_url': data['redirect_url'], 'tenant_isolation': 'enabled'}}
''')

add('app/seed/bootstrap.py', '''
from sqlalchemy import select
from app.db.session import SessionLocal
from app.models.permission import Permission
from app.models.role import Role

PERMISSIONS = [
    ('users.invite', 'Invite users'),
    ('users.impersonate', 'Impersonate users'),
    ('users.reset_pin', 'Reset kiosk pin'),
    ('roles.manage', 'Manage roles'),
    ('audit.read', 'Read audit logs'),
    ('reports.company', 'Read company reports'),
    ('api_keys.manage', 'Manage API keys'),
    ('settings.tenant', 'Manage tenant settings'),
    ('settings.kiosk', 'Manage kiosk settings'),
]

ROLE_MAP = {
    'company_owner': ['users.invite', 'users.impersonate', 'users.reset_pin', 'roles.manage', 'audit.read', 'reports.company', 'api_keys.manage', 'settings.tenant', 'settings.kiosk'],
    'hr_admin': ['users.invite', 'users.reset_pin', 'reports.company'],
    'employee': [],
}


def ensure_seed_data():
    db = SessionLocal()
    try:
        permission_objects = {}
        for key, name in PERMISSIONS:
            item = db.scalar(select(Permission).where(Permission.key == key))
            if not item:
                item = Permission(key=key, name=name, description=name)
                db.add(item)
                db.flush()
            permission_objects[key] = item
        for key, perm_keys in ROLE_MAP.items():
            role = db.scalar(select(Role).where(Role.key == key, Role.company_id.is_(None)))
            if not role:
                role = Role(key=key, name=key.replace('_', ' ').title(), company_id=None, is_system=True)
                db.add(role)
                db.flush()
            role.permissions = [permission_objects[p] for p in perm_keys]
            db.add(role)
        db.commit()
    finally:
        db.close()


if __name__ == '__main__':
    ensure_seed_data()
''')

add('templates/employee-import-template.csv', '''
first_name,last_name,email,password,employee_code,external_employee_id,payroll_employee_id,phone,role_key,provider,job_title,department,branch_id,project_ids,contract_type,employment_type,expected_hours_period,expected_hours,country,city,start_date,end_date
''')

add('alembic.ini', '''
[alembic]
script_location = alembic
sqlalchemy.url = postgresql+psycopg://postgres:postgres@localhost:5432/attendio_auth

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers = console
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
''')

add('alembic/env.py', '''
from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context
from app.core.config import settings
from app.db.session import Base
from app.models import base  # noqa

config = context.config
config.set_main_option('sqlalchemy.url', settings.DATABASE_URL)
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option('sqlalchemy.url')
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(config.get_section(config.config_ini_section, {}), prefix='sqlalchemy.', poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
''')

add('alembic/script.py.mako', '''
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}
"""
from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
''')

add('alembic/versions/0001_initial.py', '''
"""initial

Revision ID: 0001_initial
Revises: 
Create Date: 2026-04-21
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0001_initial'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('companies',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('name', sa.String(length=150), nullable=False),
        sa.Column('slug', sa.String(length=100), nullable=False),
        sa.Column('domain', sa.String(length=150), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('employee_sequence', sa.Integer(), nullable=False),
        sa.Column('employee_code_prefix', sa.String(length=20), nullable=False),
        sa.Column('metadata', sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('domain'),
        sa.UniqueConstraint('slug')
    )
    op.create_index(op.f('ix_companies_slug'), 'companies', ['slug'], unique=False)

    op.create_table('permissions',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('key', sa.String(length=120), nullable=False),
        sa.Column('name', sa.String(length=150), nullable=False),
        sa.Column('description', sa.String(length=255), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('key')
    )

    op.create_table('roles',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('key', sa.String(length=100), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('description', sa.String(length=255), nullable=True),
        sa.Column('company_id', sa.Uuid(), nullable=True),
        sa.Column('is_system', sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('key', 'company_id', name='roles_key_company_uq')
    )

    op.create_table('users',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('company_id', sa.Uuid(), nullable=False),
        sa.Column('keycloak_user_id', sa.String(length=64), nullable=True),
        sa.Column('employee_code', sa.String(length=80), nullable=True),
        sa.Column('external_employee_id', sa.String(length=80), nullable=True),
        sa.Column('payroll_employee_id', sa.String(length=80), nullable=True),
        sa.Column('first_name', sa.String(length=80), nullable=False),
        sa.Column('last_name', sa.String(length=80), nullable=False),
        sa.Column('email', sa.String(length=150), nullable=False),
        sa.Column('password_hash', sa.String(length=255), nullable=True),
        sa.Column('phone', sa.String(length=50), nullable=True),
        sa.Column('provider', sa.String(length=20), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('email_verified', sa.Boolean(), nullable=False),
        sa.Column('mfa_enabled', sa.Boolean(), nullable=False),
        sa.Column('mfa_secret', sa.String(length=255), nullable=True),
        sa.Column('login_attempts', sa.Integer(), nullable=False),
        sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True),
        sa.Column('metadata', sa.JSON(), nullable=False),
        sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('company_id', 'email', name='users_company_email_uq'),
        sa.UniqueConstraint('company_id', 'employee_code', name='users_company_employee_code_uq'),
        sa.UniqueConstraint('company_id', 'external_employee_id', name='users_company_external_employee_id_uq'),
        sa.UniqueConstraint('company_id', 'payroll_employee_id', name='users_company_payroll_employee_id_uq')
    )
    op.create_index(op.f('ix_users_company_id'), 'users', ['company_id'], unique=False)
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=False)

    op.create_table('user_roles',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('role_id', sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(['role_id'], ['roles.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'role_id', name='user_role_uq')
    )

    op.create_table('role_permissions',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('role_id', sa.Uuid(), nullable=False),
        sa.Column('permission_id', sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(['permission_id'], ['permissions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['role_id'], ['roles.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('role_id', 'permission_id', name='role_permission_uq')
    )

    op.create_table('refresh_sessions',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('token_hash', sa.String(length=255), nullable=False),
        sa.Column('device_info', sa.JSON(), nullable=False),
        sa.Column('ip_address', sa.String(length=100), nullable=True),
        sa.Column('user_agent', sa.String(length=500), nullable=True),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_refresh_sessions_token_hash'), 'refresh_sessions', ['token_hash'], unique=False)

    op.create_table('audit_logs',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('company_id', sa.Uuid(), nullable=True),
        sa.Column('actor_user_id', sa.Uuid(), nullable=True),
        sa.Column('action', sa.String(length=120), nullable=False),
        sa.Column('entity_type', sa.String(length=100), nullable=False),
        sa.Column('entity_id', sa.String(length=100), nullable=True),
        sa.Column('ip_address', sa.String(length=100), nullable=True),
        sa.Column('user_agent', sa.String(length=500), nullable=True),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )

    op.create_table('login_history',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=True),
        sa.Column('email', sa.String(length=150), nullable=False),
        sa.Column('company_slug', sa.String(length=100), nullable=True),
        sa.Column('provider', sa.String(length=50), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('ip_address', sa.String(length=100), nullable=True),
        sa.Column('user_agent', sa.String(length=500), nullable=True),
        sa.Column('failure_reason', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )

    op.create_table('verification_tokens',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('company_id', sa.Uuid(), nullable=False),
        sa.Column('type', sa.String(length=50), nullable=False),
        sa.Column('token_hash', sa.String(length=255), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('consumed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('metadata', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_verification_tokens_token_hash'), 'verification_tokens', ['token_hash'], unique=False)

    op.create_table('api_keys',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('company_id', sa.Uuid(), nullable=False),
        sa.Column('created_by_user_id', sa.Uuid(), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('prefix', sa.String(length=20), nullable=False),
        sa.Column('key_hash', sa.String(length=255), nullable=False),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('scopes', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    op.drop_table('api_keys')
    op.drop_index(op.f('ix_verification_tokens_token_hash'), table_name='verification_tokens')
    op.drop_table('verification_tokens')
    op.drop_table('login_history')
    op.drop_table('audit_logs')
    op.drop_index(op.f('ix_refresh_sessions_token_hash'), table_name='refresh_sessions')
    op.drop_table('refresh_sessions')
    op.drop_table('role_permissions')
    op.drop_table('user_roles')
    op.drop_index(op.f('ix_users_email'), table_name='users')
    op.drop_index(op.f('ix_users_company_id'), table_name='users')
    op.drop_table('users')
    op.drop_table('roles')
    op.drop_table('permissions')
    op.drop_index(op.f('ix_companies_slug'), table_name='companies')
    op.drop_table('companies')
''')

for path, content in files.items():
    file_path = root / path
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content)

print(f'Wrote {len(files)} files to {root}')
