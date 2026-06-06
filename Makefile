.PHONY: up down reset-local logs rebuild test smoke migrate seed format local minio init-prod-secrets sync-env sync-frontend-env

up:
	docker compose up --build -d

down:
	docker compose down

reset-local:
	@echo "This deletes local Docker database/storage volumes. Never run this on production."
	docker compose down -v

logs:
	docker compose logs -f --tail=200

rebuild:
	docker compose build --no-cache

smoke:
	bash ./scripts/smoke.sh

test:
	bash ./scripts/test-all.sh

migrate:
	docker compose exec auth-service alembic upgrade head
	docker compose exec attendance-service alembic upgrade head
	docker compose exec leave-service alembic upgrade head

seed:
	docker compose exec auth-service python -m app.seed.bootstrap

local:
	bash ./scripts/run-local.sh

minio:
	docker compose --env-file ./.env -f ./docker-compose.yml up -d minio

init-prod-secrets:
	ALLOW_PROD_SECRET_BOOTSTRAP=true python3 ./scripts/render-production-env.py --env-file ./.env --ensure-secrets >/dev/null

sync-env:
	bash ./scripts/sync-backend-env-secret.sh
	bash ./scripts/sync-frontend-env-secret.sh

sync-frontend-env:
	bash ./scripts/sync-frontend-env-secret.sh
