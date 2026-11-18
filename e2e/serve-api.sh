#!/bin/sh
# 通しのテストの api を起動する。Playwright の webServer から呼ばれる（環境変数も Playwright が渡す）。
# 1. web をエミュレータ向けにビルドして .web/ に置く（本番と同じく api から配る）
# 2. e2e 用の DB を空にして、表を作り、ゲスト用のデモデータを入れる
# 3. api を起動する
set -eu

here=$(cd "$(dirname "$0")" && pwd)

cd "$here/../web"
npm run build -- --outDir "$here/.web" --emptyOutDir

cd "$here/../api"
uv run python -m scripts.reset_e2e_db
uv run python -m scripts.seed_demo
exec uv run uvicorn app.main:app --port "$E2E_API_PORT"
