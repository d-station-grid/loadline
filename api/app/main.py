from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.config import get_settings
from app.routers import auth


def create_app(static_dir: str | None = None) -> FastAPI:
    """アプリを組み立てる。static_dir はテストで差し替えるための引数。"""
    settings = get_settings()
    app = FastAPI(title="loadline API")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["Authorization"],
    )
    app.include_router(auth.router)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    # 本番では web のビルド成果物を同じサービスから配る。API のパスが先に引かれ、残りがここに落ちる
    static = settings.static_dir if static_dir is None else static_dir
    if static:
        app.mount("/", StaticFiles(directory=static, html=True), name="web")

    return app


app = create_app()
