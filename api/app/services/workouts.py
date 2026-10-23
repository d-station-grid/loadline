from datetime import datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Workout, WorkoutHeartRate


async def list_workouts(
    session: AsyncSession,
    user_id: int,
    since: datetime | None = None,
    until: datetime | None = None,
    before_id: int | None = None,
    limit: int = 100,
) -> list[Workout]:
    """本人のワークアウトを新しい順に。since 以上、until 未満で絞る。

    開始時刻が同じものは id の大きい順。before_id を until と一緒に渡すと、開始時刻が
    until と同じで id が before_id より小さいものも含める。前のページの最後の 1 件の
    開始時刻と id を渡せば、開始時刻がそろった記録がページの境目にあっても抜けない。
    """
    stmt = select(Workout).where(Workout.user_id == user_id)
    if since is not None:
        stmt = stmt.where(Workout.started_at >= since)
    if until is not None and before_id is not None:
        stmt = stmt.where(
            or_(
                Workout.started_at < until,
                and_(Workout.started_at == until, Workout.id < before_id),
            )
        )
    elif until is not None:
        stmt = stmt.where(Workout.started_at < until)
    stmt = stmt.order_by(Workout.started_at.desc(), Workout.id.desc()).limit(limit)
    return list(await session.scalars(stmt))


async def get_workout(session: AsyncSession, user_id: int, workout_id: int) -> Workout | None:
    """本人のものだけ返す。他人の id は None。"""
    return await session.scalar(
        select(Workout).where(Workout.id == workout_id, Workout.user_id == user_id)
    )


async def heart_rates(session: AsyncSession, workout_id: int) -> list[WorkoutHeartRate]:
    stmt = (
        select(WorkoutHeartRate)
        .where(WorkoutHeartRate.workout_id == workout_id)
        .order_by(WorkoutHeartRate.recorded_at)
    )
    return list(await session.scalars(stmt))
