from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Workout, WorkoutHeartRate
from app.schemas.workouts import ZoneSeconds

# 心拍は 1 分ごとに届くので、1 サンプルを 60 秒と数える
SAMPLE_SEC = 60


def zone_seconds(
    samples: Sequence[WorkoutHeartRate], boundary_1: int | None, boundary_2: int | None
) -> ZoneSeconds | None:
    """強度ごとの時間。avg_bpm が boundary_1 未満は low、boundary_2 未満は mid、それ以上は high。

    境目は設定で入れるもので、2 つそろうまでは計算しない（None を返す）。
    """
    if boundary_1 is None or boundary_2 is None:
        return None
    low = mid = high = 0
    for s in samples:
        if s.avg_bpm < boundary_1:
            low += SAMPLE_SEC
        elif s.avg_bpm < boundary_2:
            mid += SAMPLE_SEC
        else:
            high += SAMPLE_SEC
    return ZoneSeconds(low=low, mid=mid, high=high)


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
