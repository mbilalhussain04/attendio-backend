# Shared contracts

This folder holds cross-service contracts for a low-coupling microservices setup.

## Principles

- Services own their own database.
- Services never read another service database directly.
- Communication is done through HTTP for request-response and Redis pub/sub for async events.
- Any future service should publish domain events instead of creating tight runtime dependencies.

## Current service boundaries

- `auth-service` owns companies, users, roles, permissions, sessions, MFA, SSO.
- `attendance-service` owns attendance records, breaks, corrections, policies, geofences, shifts, kiosk attendance.

## Recommended future events

- `auth.user.created`
- `auth.user.updated`
- `auth.employee.created`
- `attendance.checkin.created`
- `attendance.checkout.created`
- `attendance.correction.requested`
- `attendance.correction.approved`
