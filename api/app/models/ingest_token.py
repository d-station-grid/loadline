from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class IngestToken(Base):
    """Health Auto Export が記録を送るときに付けるトークン。値は持たず、ハッシュだけを保存する。"""

    __tablename__ = "ingest_tokens"
    # 有効なトークンは利用者ごとに 1 本。発行の直列化（行ロック）を通らない経路があっても破れない
    __table_args__ = (
        Index(
            "uq_ingest_tokens_active_user",
            "user_id",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )

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
