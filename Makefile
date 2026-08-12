# Every command you need, discoverable via `make help`.
# Using make here is deliberate: it gives you and CI a single vocabulary,
# so "how do I run the tests" has exactly one answer.

.DEFAULT_GOAL := help
.PHONY: help up down logs shell psql migrate makemigration downgrade \
        test test-unit test-integration lint fmt typecheck check seed \
        load-test nuke build-prod lock

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# --- stack -------------------------------------------------------------------

up:  ## Start the stack (db + api) in the background
	docker compose up -d --build db api
	@echo "api:  http://localhost:8000"
	@echo "docs: http://localhost:8000/docs"

down:  ## Stop the stack, keep data
	docker compose down

nuke:  ## Stop the stack and destroy all data volumes
	docker compose down -v

logs:  ## Tail api logs
	docker compose logs -f api

shell:  ## Shell inside the api container
	docker compose exec api bash

psql:  ## Interactive psql against the dev database
	docker compose exec db psql -U ledger -d ledger

# --- dependencies ------------------------------------------------------------

# Runs on the host rather than in a container: uv resolves for the target
# interpreter via --python-version, so the host's own Python is irrelevant,
# and this is the one thing you need before an image exists to run it in.
lock:  ## Regenerate the lockfiles from pyproject.toml
	@command -v uv >/dev/null || \
		(echo 'uv not installed: curl -LsSf https://astral.sh/uv/install.sh | sh'; exit 1)
	uv pip compile pyproject.toml --python-version 3.12 -o requirements.lock
	uv pip compile pyproject.toml --extra dev --python-version 3.12 -o requirements-dev.lock

# --- migrations --------------------------------------------------------------

migrate:  ## Apply all pending migrations
	docker compose run --rm api alembic upgrade head

makemigration:  ## Autogenerate a migration: make makemigration m="add accounts"
	@test -n "$(m)" || (echo 'usage: make makemigration m="message"'; exit 1)
	docker compose run --rm api alembic revision --autogenerate -m "$(m)"

downgrade:  ## Roll back one migration
	docker compose run --rm api alembic downgrade -1

# --- quality -----------------------------------------------------------------

test:  ## Run the full suite (spins up the throwaway test db)
	docker compose up -d db-test
	docker compose run --rm \
		-e LEDGER_DATABASE_URL=postgresql+psycopg://ledger:ledger@db-test:5432/ledger_test \
		api pytest

test-unit:  ## Fast tests only, no database
	docker compose run --rm api pytest -m "not integration and not concurrency"

test-integration:  ## Database-backed tests only
	docker compose up -d db-test
	docker compose run --rm \
		-e LEDGER_DATABASE_URL=postgresql+psycopg://ledger:ledger@db-test:5432/ledger_test \
		api pytest -m integration

lint:  ## Lint
	docker compose run --rm api ruff check app tests

fmt:  ## Auto-format and fix what can be fixed
	docker compose run --rm api ruff format app tests
	docker compose run --rm api ruff check --fix app tests

typecheck:  ## Static type check
	docker compose run --rm api mypy app

check: lint typecheck test  ## Everything CI runs

# --- misc --------------------------------------------------------------------

seed:  ## Load the demo chart of accounts
	docker compose run --rm api python -m scripts.seed

load-test:  ## Hammer the API (requires the stack to be up)
	docker compose run --rm api locust -f loadtest/locustfile.py \
		--headless -u 50 -r 10 -t 60s --host http://api:8000

build-prod:  ## Build the production image
	docker build --target prod -t ledger:prod .
