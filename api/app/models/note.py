from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Note(Base):
    """利用者が日付ごとに書くメモ。体調や出来事を残し、振り返りの材料にする。

    ワークアウトとは外部キーでつながない。その日のメモは、利用者のタイムゾーンでの日付で探す。
    """

    __tablename__ = "notes"
    # メモは 1 日 1 件
    __table_args__ = (UniqueConstraint("user_id", "date"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    # 利用者のタイムゾーンでの日付
    date: Mapped[date] = mapped_column(Date)
    # チャートに出す短いラベル。付けなければ NULL
    label: Mapped[str | None] = mapped_column(String(12))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
