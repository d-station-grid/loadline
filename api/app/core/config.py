from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    database_url: str = ""
    firebase_project_id: str = ""
    cors_origins: list[str] = []
    static_dir: str = ""
    # 振り返りのセリフを書く Gemini（Vertex AI）。プロジェクトが空なら呼ばずに定型にする
    gemini_project: str = ""
    # 試作で動きを確かめた global。東京（asia-northeast1）で同じモデルを呼べるかは未確認
    gemini_location: str = "global"
    # 混雑や失敗のときは、先頭から順に試す
    gemini_models: list[str] = ["gemini-3.8-flash", "gemini-3.5-flash", "gemini-2.5-flash"]
    # 振り返り 1 通に待つ上限。超えたら定型にする
    gemini_timeout_sec: float = 60.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
