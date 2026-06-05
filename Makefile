.PHONY: up down logs rebuild test smoke migrate seed format local minio prod-env sync-env sync-prod-env sync-frontend-env

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
	docker compose --env-file ./.env -f ./docker-compose.yml up -d minio

sync-env:
	$(MAKE) sync-prod-env
	bash ./scripts/sync-frontend-env-secret.sh

prod-env:
	@if [ -f .env.production ]; then \
		echo ".env.production already exists. Edit it if you need to change production secrets."; \
	else \
		python3 ./scripts/create-production-env.py --output .env.production; \
	fi

sync-prod-env: prod-env
	BACKEND_ENV_FILE=./.env.production bash ./scripts/sync-backend-env-secret.sh

sync-frontend-env:
	bash ./scripts/sync-frontend-env-secret.sh
