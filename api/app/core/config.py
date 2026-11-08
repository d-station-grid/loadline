from functools import lru_cache

from pydantic import field_validator
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
    # Gemini が書いたセリフを確かめる Jev（TypeSafe AI）。キーが空なら確かめられないので、
    # Gemini が書いても話さずに定型にする
    typesafe_api_key: str = ""
    typesafe_model: str = "jev-latest"
    # 確かめるのに待つ上限。超えたら定型にする
    typesafe_timeout_sec: float = 15.0
    # 内部の窓口（/internal）を呼べるのは、Cloud Scheduler と Cloud Tasks が付ける OIDC
    # トークンだけ。宛先（audience）と、トークンを出すサービスアカウントのメールアドレス。
    # どちらかが空なら、内部の窓口はすべて 401 にする
    internal_audience: str = ""
    internal_caller_email: str = ""
    # 振り返りを 1 人ずつ作るタスクを積むキュー（projects/.../locations/.../queues/...）。
    # 空なら積まずに、見つけた相手をログに出すだけ
    tasks_queue: str = ""
    # 振り返りのセリフを読み上げる tts（Kokoro、Cloud Run）の URL。空なら声にしない
    tts_url: str = ""
    # 読み上げ 1 回に待つ上限（429 のやり直しを含む）。超えたら声なし（文字だけ）にする
    tts_timeout_sec: float = 45.0
    # 振り返りの音声を置くバケット（gs:// は付けない）。空なら声にしない
    audio_bucket: str = ""
    # 音声の署名付き URL の期限
    audio_url_ttl_sec: int = 3600

    @field_validator("internal_audience", "tts_url")
    @classmethod
    def _drop_trailing_slash(cls, value: str) -> str:
        # Tasks が付ける宛先と窓口が検証する宛先は、文字列が完全に一致しないと 401 になる。
        # どちらもこの値を使うので、ここで 1 回だけそろえる。tts の URL も ID トークンの
        # 宛先にするので同じ。後ろにパスを足すときに // にもならない
        return value.rstrip("/")


@lru_cache
def get_settings() -> Settings:
    return Settings()
