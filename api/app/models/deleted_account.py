from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class DeletedAccount(Base):
    """アカウントを消した人の Firebase の uid。

    Firebase の利用者を消しても、出してある ID トークンは期限（1 時間）まで検証を通る。
    そのトークンで行を作り直さないよう、uid だけを少しの間残して拒否する。
    1 日たったら dispatch が消す。
    """

    __tablename__ = "deleted_accounts"

    firebase_uid: Mapped[str] = mapped_column(String(128), primary_key=True)
    deleted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
