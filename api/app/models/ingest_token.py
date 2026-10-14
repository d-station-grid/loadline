from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class IngestToken(Base):
    """Health Auto Export が記録を送るときに付けるトークン。値は持たず、ハッシュだけを保存する。"""

    __tablename__ = "ingest_tokens"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # SHA-256 の 16 進（64 文字）。DB が漏れてもトークンは分からない
    token_digest: Mapped[str] = mapped_column(String(64), unique=True)
    # 設定画面で「…abcd」とマスク表示するための末尾 4 文字
    last_four: Mapped[str] = mapped_column(String(4))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # 再発行で無効にした日時。NULL なら有効
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
