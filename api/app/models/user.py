from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Index,
    Integer,
    SmallInteger,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        # デモの利用者は 1 人だけ。ゲストは全員この 1 人として扱うので、2 人いると決まらない
        Index("uq_users_demo", "is_demo", unique=True, postgresql_where=text("is_demo")),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # Google アカウント 1 つにつき利用者は 1 人。デモ用の行は NULL
    firebase_uid: Mapped[str | None] = mapped_column(String(128), unique=True)
    email: Mapped[str] = mapped_column(String(255))
    # ゲストに見せるデモデータの持ち主
    is_demo: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))

    # 設定。心拍の 4 つは設定画面で入れるまで NULL。強度の計算はこれがそろってから
    max_heart_rate: Mapped[int | None] = mapped_column(Integer)
    resting_heart_rate: Mapped[int | None] = mapped_column(Integer)
    zone_boundary_1: Mapped[int | None] = mapped_column(Integer)  # Low と Mid の境目
    zone_boundary_2: Mapped[int | None] = mapped_column(Integer)  # Mid と High の境目
    timezone: Mapped[str] = mapped_column(String(64), server_default="Asia/Tokyo")
    review_weekday: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))  # 0 が月曜
    send_notes_to_ai: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    # Health Auto Export からの取り込みが最後に成功した日時。保存と同じトランザクションで書く。
    # 取り込み用トークンの last_used_at は認証の時点で進むので、失敗した送信でも変わる
    last_ingested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
