from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ReviewStatus(StrEnum):
    """振り返りを作る処理の状態。"""

    GENERATING = "generating"
    COMPLETED = "completed"
    FAILED = "failed"


class WeeklyReview(Base):
    """週に 1 回、アバターが話す振り返り。

    判定に使った数値は保存しない。ワークアウトと心拍の設定から、いつでも計算し直せる。
    """

    __tablename__ = "weekly_reviews"
    # 同じ期間の振り返りを、二重に作らない
    __table_args__ = (UniqueConstraint("user_id", "period_start"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    # 振り返る 7 日間の両端。利用者のタイムゾーンでの日付
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    # コードで判定した状況。app.domain.situation.Situation の値
    situation: Mapped[str] = mapped_column(String(32))
    # アバターのセリフ。字幕にも使う
    script: Mapped[str] = mapped_column(Text)
    # Cloud Storage 上の音声。声にするまでは NULL
    audio_path: Mapped[str | None] = mapped_column(String(512))
    # ReviewStatus の値
    status: Mapped[str] = mapped_column(String(16))
    # 人が書いた定型のセリフなら true
    is_fallback: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class WeeklyReviewOption(Base):
    """振り返りのあとに並べる、その週の過ごし方の選択肢。1 つの振り返りに 2〜3 個。"""

    __tablename__ = "weekly_review_options"
    # 並びの位置は、1 つの振り返りの中で重ねない
    __table_args__ = (UniqueConstraint("weekly_review_id", "position"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    weekly_review_id: Mapped[int] = mapped_column(
        ForeignKey("weekly_reviews.id", ondelete="CASCADE")
    )
    # 並びの位置。0 から
    position: Mapped[int] = mapped_column(SmallInteger)
    # ボタンの文字
    label: Mapped[str] = mapped_column(String(64))
    # ボタンの下の 1 文
    description: Mapped[str] = mapped_column(String(255))
    # 本人が選んだものだけに入る
    selected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
