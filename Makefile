PY ?= .venv/bin/python
TEST_DATABASE_URL ?= postgresql+psycopg://formmanager_test_app:test_app@127.0.0.1:55433/formmanager_test
export TEST_DATABASE_URL

.PHONY: venv test test-unit test-integration test-concurrency test-db-up test-db-down \
        lint format typecheck security-check check up down logs backup smoke

venv:
	python3.12 -m venv .venv
	$(PY) -m pip install -r requirements-dev.txt

test-db-up:
	docker compose -f docker-compose.test.yml up -d --wait

test-db-down:
	docker compose -f docker-compose.test.yml down -v

test: test-db-up
	$(PY) -m pytest

test-unit:
	$(PY) -m pytest tests/unit

test-integration: test-db-up
	$(PY) -m pytest tests/integration

test-concurrency: test-db-up
	$(PY) -m pytest tests/concurrency -v

lint:
	$(PY) -m ruff check .
	$(PY) -m black --check .

format:
	$(PY) -m ruff check --fix .
	$(PY) -m black .

typecheck:
	$(PY) -m mypy --strict app

security-check:
	$(PY) -m bandit -q -c pyproject.toml -r app
	$(PY) -m pip_audit -r requirements.txt

check: lint typecheck security-check test

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f --tail=200

backup:
	scripts/backup.sh

# Requires a running stack: BASE_URL, ADMIN_USER, ADMIN_PASS (CURL_INSECURE=1 for localhost).
smoke:
	scripts/smoke_test.sh
