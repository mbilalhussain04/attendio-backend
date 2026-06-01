.PHONY: up down logs rebuild test smoke migrate seed format local minio

up:
	docker compose up --build -d

down:
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
	docker compose --env-file ./.env.local -f ./docker-compose.yml up -d minio
