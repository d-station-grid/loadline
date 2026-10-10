# loadline tts: Kokoro を組み込んだ FastAPI。api と同じ python:3.12-slim を土台にする
FROM python:3.12-slim

# uv は公式イメージから実行ファイルだけ取り込む（手元の uv と同じ版）
COPY --from=ghcr.io/astral-sh/uv:0.12.1 /uv /bin/uv

ENV PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app

# 依存だけ先に入れる。main.py を直してもこの層はキャッシュが効く
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# モデル（約 350MB）はイメージに含める。起動のたびにダウンロードしない
COPY main.py kokoro-v1.0.onnx voices-v1.0.bin ./

ENV PATH="/app/.venv/bin:$PATH"
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}"]
