# attendance-service

This service is intended to run from the root `Services/docker-compose.yml` using the shared root `.env` file.

This service is intended to run inside the sibling `Services/` monorepo with auth-service. Use `cd .. && docker compose up --build` from the `Services` folder for the combined stack.

# Attendio Attendance Service - FastAPI

FastAPI conversion of the attendance microservice with PostgreSQL, Alembic, Swagger tags, tenant-aware auth context, reports, kiosk, policy, geofence, exports, audit logs, and offline sync.

## Features
- Check in, check out, breaks, manual entries
- Correction requests and approvals
- Attendance locks
- Dashboard, timesheet, daily summary, weekly and monthly reports
- Overtime, absence, branch comparison, shift variance, anomaly reports
- Company attendance policy
- Holidays, geofences, shifts, kiosk devices
- Offline sync queue and processing
- Audit logs and notification events
- Host and token based tenant isolation

## Local run
```bash
cp .env.example .env
pip install -r requirements.txt
alembic upgrade head
python run.py
```

Swagger:
- http://localhost:8001/docs

## Docker
```bash
docker compose up --build
```

## Auth integration
This service validates the JWT locally using `JWT_ACCESS_SECRET` and can optionally enrich the user profile from the auth service through `AUTH_SERVICE_URL`.

Expected token claims include:
- `sub`
- `companyId`
- `companySlug`
- `permissions`
- `roles`
- `email`

## Multi tenant isolation
- Requests require a tenant aware token with `companyId`
- If the incoming host resolves to a different tenant slug than the token, access is blocked
- All queries are additionally scoped by `company_id`
