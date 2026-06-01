# Event channels

Current broker options inside the stack:

- Redis for lightweight pub sub and caching
- RabbitMQ for stronger queueing and future workflow orchestration

## Suggested channels or exchanges

### Redis
- `attendio.events`

### RabbitMQ exchanges
- `attendio.domain`
- `attendio.notifications`
- `attendio.reporting`

## Routing keys

- `auth.user.created`
- `auth.employee.created`
- `attendance.checkin.created`
- `attendance.checkout.created`
- `attendance.correction.approved`
