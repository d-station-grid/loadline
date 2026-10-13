from pydantic import BaseModel, ConfigDict


class UserOut(BaseModel):
    """ログインした本人に返す情報。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
