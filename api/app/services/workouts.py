from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Workout, WorkoutHeartRate


async def list_workouts(
    session: AsyncSession,
    user_id: int,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 100,
) -> list[Workout]:
    """本人のワークアウトを新しい順に。since 以上、until 未満で絞る。"""
    stmt = select(Workout).where(Workout.user_id == user_id)
    if since is not None:
        stmt = stmt.where(Workout.started_at >= since)
    if until is not None:
        stmt = stmt.where(Workout.started_at < until)
    stmt = stmt.order_by(Workout.started_at.desc()).limit(limit)
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
