# Auth <-> Attendance contracts

## Synchronous lookup examples

Attendance may call auth-service only for tenant safe identity enrichment when needed:
- resolve employee profile for current token
- verify tenant and permission context
- fetch display name or employee code for responses

## Event driven examples

Auth emits:
- `user.created`
- `user.updated`
- `employee.created`
- `employee.updated`
- `company.created`
- `role.updated`

Attendance emits:
- `attendance.checked_in`
- `attendance.checked_out`
- `attendance.corrected`
- `attendance.locked`
- `attendance.export.completed`

These events should be versioned and backward compatible.
