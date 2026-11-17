from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.responses import Response
from starlette.types import Scope

from app.core.config import get_settings
from app.routers import auth, dashboard, ingest, internal, me, notes, reviews, workouts
from app.routers import settings as settings_router


class WebFiles(StaticFiles):
    """web のビルド成果物を、キャッシュの指示を付けて配る。

    assets/ の JS と CSS はファイル名に中身のハッシュが入るので、1 年使い回してよい。
    それ以外（index.html、favicon、アバターのモデル）は名前が変わらないので、毎回確かめさせる。
    index.html が使い回されると、デプロイのあとも古い JS を読み続ける。
    変わっていなければ 304 が返るので、確かめる分の重さはほとんどない。
    """

    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        if path.startswith("assets/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            response.headers["Cache-Control"] = "no-cache"
        return response


def create_app(static_dir: str | None = None) -> FastAPI:
    """アプリを組み立てる。static_dir はテストで差し替えるための引数。"""
    settings = get_settings()
    app = FastAPI(title="loadline API")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["Authorization", "X-Guest-Language"],
    )
    app.include_router(auth.router)
    app.include_router(dashboard.router)
    app.include_router(ingest.router)
    app.include_router(internal.router)
    app.include_router(me.router)
    app.include_router(notes.router)
    app.include_router(reviews.router)
    app.include_router(settings_router.router)
    app.include_router(workouts.router)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    # 本番では web のビルド成果物を同じサービスから配る。API のパスが先に引かれ、残りがここに落ちる
    static = settings.static_dir if static_dir is None else static_dir
    if static:
        app.mount("/", WebFiles(directory=static, html=True), name="web")

    return app


app = create_app()
