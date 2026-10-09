.PHONY: check check-api check-web fmt types dev dev-api dev-web

check: check-api check-web

check-api:
	cd api && uv run ruff check . && uv run ruff format --check . && uv run mypy app tests scripts && uv run pytest

check-web:
	cd web && npm run check

fmt:
	cd api && uv run ruff format . && uv run ruff check --fix .
	cd web && npm run format

types:
	cd api && uv run python -m scripts.export_openapi
	cd web && npm run generate:api

dev:
	$(MAKE) -j2 dev-api dev-web

dev-api:
	cd api && uv run uvicorn app.main:app --reload

dev-web:
	cd web && npm run dev
