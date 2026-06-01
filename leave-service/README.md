# leave-service

Leave requests, policy, entitlements, balances, and approvals live in this service.
It keeps a separate `attendio_leave` database and only uses auth token/profile
contracts and the storage service for attachments.

## Local run

From `Services/`, the normal local stack command starts this service too:

```bash
cp .env.local.example .env.local
bash ./scripts/local-install.sh
make local
```

Direct service run:

```bash
cd leave-service
python -m alembic upgrade head
python run.py
```

Local Swagger: `http://localhost:8004/docs`

## Docker

From `Services/`:

```bash
docker compose up --build leave-service
```

The root nginx gateway exposes `/api/v1/leave/` and unified docs include the
Leave OpenAPI document.
