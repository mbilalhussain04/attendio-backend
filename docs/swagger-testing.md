# Swagger Testing Guide

## Combined Swagger

After `docker compose up --build`, open:

- `http://localhost/docs`

This merges both services into a single Swagger UI.

## Test order

### 1. Health
- `GET /api/v1/health`
- `GET /health`
- `GET /health` on gateway is also available through `http://localhost/docs`

### 2. Auth bootstrap
Use `POST /api/v1/auth/bootstrap-company`

```json
{
  "company_name": "Attendio Demo",
  "owner_first_name": "Owner",
  "owner_last_name": "Admin",
  "owner_email": "owner@example.com",
  "owner_password": "Admin@12345"
}
```

Expected:
- slug auto generated
- owner created
- roles and permissions seeded

### 3. Login
Use `POST /api/v1/auth/login`

```json
{
  "email": "owner@example.com",
  "password": "Admin@12345"
}
```

Expected:
- access token
- refresh token
- display name message

Copy bearer token into Swagger `Authorize`.

### 4. Auth smoke path
- `GET /api/v1/auth/me`
- `GET /api/v1/auth/permissions`
- `GET /api/v1/admin/roles`
- `POST /api/v1/admin/api-keys`
- `GET /api/v1/admin/audit-logs`

### 5. Attendance smoke path
With the same token:
- `GET /health`
- `GET /api/v1/attendance/me/today`
- `POST /api/v1/attendance/check-in`
- `POST /api/v1/attendance/breaks/start`
- `POST /api/v1/attendance/breaks/end`
- `POST /api/v1/attendance/check-out`
- `GET /api/v1/attendance/reports/daily-summary`

### 6. Isolation check
- Create a second tenant using bootstrap.
- Login through its own domain or isolate through token context.
- Confirm records from tenant A do not appear in tenant B queries.

### 7. Kiosk and advanced auth
- `POST /api/v1/kiosk/set-pin`
- `POST /api/v1/kiosk/login`
- `POST /api/v1/auth/mfa/setup`
- `POST /api/v1/auth/mfa/verify`
- `GET /api/v1/auth/sso/google/start`
- `GET /api/v1/auth/sso/microsoft/start`

## Useful URLs

- Combined docs: `http://localhost/docs`
- Auth docs: `http://localhost:8000/docs`
- Attendance docs: `http://localhost:8001/docs`
- RabbitMQ UI: `http://localhost:15672`
