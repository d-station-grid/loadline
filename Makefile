.PHONY: check check-api check-web fmt types dev dev-api dev-web check-tts check-e2e cov e2e

check: check-api check-web check-tts check-e2e

check-api:
	cd api && uv run ruff check . && uv run ruff format --check . && uv run mypy app tests scripts && uv run pytest

check-web:
	cd web && npm run check

check-tts:
	cd tts && uv run ruff check . && uv run ruff format --check .

check-e2e:
	cd e2e && npm run check

# 通しのテスト。Postgres を起動し、Auth のエミュレータと api（web を同梱）は Playwright が起動する。
# DB は開発用とは別の loadline_e2e を毎回作り直す
e2e:
	docker compose up -d --wait db
	cd e2e && npm test

cov:
	cd api && uv run pytest --cov --cov-report=term-missing
	cd web && npm run test:coverage

fmt:
	cd api && uv run ruff format . && uv run ruff check --fix .
	cd web && npm run format
	cd tts && uv run ruff format . && uv run ruff check --fix .
	cd e2e && npm run format

types:
	cd api && uv run python -m scripts.export_openapi
	cd web && npm run generate:api

dev:
	$(MAKE) -j2 dev-api dev-web

dev-api:
	cd api && uv run uvicorn app.main:app --reload

dev-web:
	cd web && npm run dev
