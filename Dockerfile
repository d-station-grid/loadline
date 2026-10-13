# loadline: web をビルドして api に同梱し、Cloud Run の 1 つのサービスとして動かす
# 1 段目: web のビルド
FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
# Firebase の設定は公開前提の値。ビルド時に埋め込む。VITE_API_URL は空のまま（同じオリジン）
ARG VITE_FIREBASE_API_KEY
ARG VITE_FIREBASE_AUTH_DOMAIN
ARG VITE_FIREBASE_PROJECT_ID
ARG VITE_FIREBASE_APP_ID
RUN npm run build

# 2 段目: api。tts と同じ python:3.12-slim と uv
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.1 /uv /bin/uv
ENV PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app

# 依存だけ先に入れる。app/ を直してもこの層はキャッシュが効く
COPY api/pyproject.toml api/uv.lock ./
RUN uv sync --frozen --no-dev

COPY api/app ./app
COPY api/alembic ./alembic
COPY api/alembic.ini ./
# web のビルド成果物。api は STATIC_DIR から配る
COPY --from=web /web/dist ./static

ENV PATH="/app/.venv/bin:$PATH" STATIC_DIR=/app/static
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
