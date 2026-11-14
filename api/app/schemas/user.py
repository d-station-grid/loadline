from pydantic import BaseModel, ConfigDict


class LoginIn(BaseModel):
    """POST /auth/login の本文。省いてもよい。"""

    # ブラウザのタイムゾーン（"America/New_York" など）。初回ログインで行を作るときだけ使う。
    # 空や知らない名前は 422 にせず、既定値で作る
    timezone: str | None = None
    # ブラウザの言語（"ja-JP" など）。初回ログインで行を作るときだけ使う。
    # 知らない言語は 422 にせず、既定値（英語）で作る
    language: str | None = None


class UserOut(BaseModel):
    """ログインした本人に返す情報。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
