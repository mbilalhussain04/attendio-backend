# Attendio Services Monorepo

Enterprise-oriented microservices workspace for the Attendio platform.

## Layout

```text
Services/
├── auth-service
├── attendance-service
├── leave-service
├── docs-gateway
├── storage-service
├── nginx
├── infra
│   └── postgres-init
├── shared
│   ├── contracts
│   ├── events
│   └── python
├── scripts
├── .env
├── .env.example
└── docker-compose.yml
```

## What is included

- Auth, attendance, leave, and storage services as separate FastAPI microservices
- Single PostgreSQL cluster with separate logical databases for low coupling
- Redis and RabbitMQ ready for async communication
- Combined Swagger UI through `docs-gateway`
- Root-only environment management
- Health checks and container dependencies
- Shared event envelope package for future services
- Pytest test suites and smoke scripts

## Start everything

```bash
cp .env.example .env
docker compose up --build
```

## Main endpoints

- Combined Swagger: `http://localhost/docs`
- Auth Swagger: `http://localhost:8000/docs`
- Attendance Swagger: `http://localhost:8001/docs`
- Storage Swagger: `http://localhost:8002/docs`
- Leave Swagger: `http://localhost:8004/docs`
- MinIO Console: `http://localhost:9001`
- RabbitMQ UI: `http://localhost:15672`

## Tests

### Local unit tests

```bash
bash ./scripts/test-all.sh
```

### Container smoke checks

```bash
bash ./scripts/smoke.sh
```

## Architecture notes

- Keep service ownership clear. Auth owns identity and tenant resolution. Attendance owns time records and reporting. Leave owns absence requests and entitlements.
- Shared code is limited to contracts and event envelope utilities. Business logic remains inside each service.
- PostgreSQL is shared at cluster level only. Each service keeps its own database to avoid migration coupling.
- Redis or RabbitMQ can be selected with `BROKER_BACKEND` from the root `.env`.


## Common requirements strategy

Common Python dependencies now live at the root:

```text
requirements/
├── common.txt
├── auth-extra.txt
├── attendance-extra.txt
├── docs-gateway.txt
└── dev.txt
```

Service requirement files only reference these root files, so version changes are done once.

## Step by step run

### Option 1: Docker, recommended

```bash
cp .env.example .env
docker compose up --build
```

Then open `http://localhost/docs`.

### Option 2: Run services without Docker

You can run the Python services directly and keep Docker as an optional path.
This still needs PostgreSQL and Redis running on your machine.

```bash
cp .env.local.example .env.local
bash ./scripts/local-install.sh
make local
```

On macOS with Homebrew, local infrastructure can be started with:

```bash
brew install postgresql@16 redis
brew services start postgresql@16
brew services start redis
```

MinIO can run locally without Docker too. Download the MinIO server binary, then start a local single-node instance:

```bash
mkdir -p ~/minio-data
MINIO_ROOT_USER=minioadmin MINIO_ROOT_PASSWORD=minioadmin minio server ~/minio-data --console-address ":9001"
```

The local services prefer MinIO at `localhost:9000` by default. With `STORAGE_BACKEND=auto`, `make local` falls back to `storage-service/.local-storage` when MinIO is not running, so profile uploads still work without Docker.

Homebrew PostgreSQL often creates a role matching your macOS username instead
of `postgres`. If you see `role "postgres" does not exist`, set these in
`.env.local`:

```text
POSTGRES_USER=your-mac-username
POSTGRES_PASSWORD=
AUTH_DATABASE_URL=postgresql+psycopg://your-mac-username@localhost:5432/attendio_auth
ATTENDANCE_DATABASE_URL=postgresql+psycopg://your-mac-username@localhost:5432/attendio_attendance
STORAGE_DATABASE_URL=postgresql+psycopg://your-mac-username@localhost:5432/attendio_storage
LEAVE_DATABASE_URL=postgresql+psycopg://your-mac-username@localhost:5432/attendio_leave
```

Local config lives in `.env.local` and overrides the Docker hostnames from `.env`.
The important local values are:

```text
AUTH_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/attendio_auth
ATTENDANCE_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/attendio_attendance
STORAGE_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/attendio_storage
LEAVE_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/attendio_leave
REDIS_URL=redis://localhost:6379/0
AUTH_SERVICE_URL=http://localhost:8000
```

Then open:

- Unified Swagger: `http://localhost:8090/docs`
- Auth Swagger: `http://localhost:8000/docs`
- Attendance Swagger: `http://localhost:8001/docs`
- Storage Swagger: `http://localhost:8002/docs`
- Leave Swagger: `http://localhost:8004/docs`

### Option 3: Run tests only

```bash
bash ./scripts/test-all.sh
```

### Option 4: Migrations manually

```bash
docker compose exec auth-service alembic upgrade head
docker compose exec attendance-service alembic upgrade head
docker compose exec leave-service alembic upgrade head
docker compose exec auth-service python -m app.seed.bootstrap
```

## Swagger testing

Full ordered Swagger checks are documented in `docs/swagger-testing.md`.
