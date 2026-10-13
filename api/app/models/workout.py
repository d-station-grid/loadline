from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Workout(Base):
    """Apple Watch で記録した 1 回のワークアウト。Health Auto Export から届く。"""

    __tablename__ = "workouts"
    # 同じ記録が何度届いても、二重に数えない
    __table_args__ = (UniqueConstraint("user_id", "external_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # Health Auto Export の id（UUID）
    external_id: Mapped[str] = mapped_column(String(64))
    # ride か run。種目名から写す
    sport: Mapped[str] = mapped_column(String(16))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    duration_sec: Mapped[int] = mapped_column(Integer)
    avg_heart_rate: Mapped[int | None] = mapped_column(Integer)
    max_heart_rate: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class WorkoutHeartRate(Base):
    """ワークアウト中の心拍。Health Auto Export の heartRateData（1 分ごと）をそのまま持つ。"""

    __tablename__ = "workout_heart_rates"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    workout_id: Mapped[int] = mapped_column(
        ForeignKey("workouts.id", ondelete="CASCADE"), index=True
    )
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    min_bpm: Mapped[int] = mapped_column(Integer)
    avg_bpm: Mapped[int] = mapped_column(Integer)
    max_bpm: Mapped[int] = mapped_column(Integer)
