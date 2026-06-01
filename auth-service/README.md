# auth-service

This service is intended to run from the root `Services/docker-compose.yml` using the shared root `.env` file.

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
