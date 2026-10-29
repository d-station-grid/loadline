from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.calendar import since_for_weeks
from app.domain.load import zone_times
from app.models import User, Workout, WorkoutHeartRate
from app.schemas.workouts import (
    HeartRateSample,
    WorkoutDetail,
    WorkoutList,
    WorkoutSummary,
    zone_seconds,
)


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


async def workout_list(
    session: AsyncSession,
    user: User,
    *,
    since: datetime | None,
    until: datetime | None,
    before_id: int | None,
    limit: int,
    weeks: int | None = None,
) -> WorkoutList:
    """一覧の 1 ページと、絞り込みに使った始まり。

    weeks を渡すと、since は利用者のタイムゾーンの今日から weeks 週前の日の 0 時になる。
    since と一緒には渡さない（router で落とす）。
    """
    if weeks is not None:
        since = since_for_weeks(weeks, ZoneInfo(user.timezone))
    rows = await list_workouts(
        session, user.id, since=since, until=until, before_id=before_id, limit=limit
    )
    return WorkoutList(items=[WorkoutSummary.model_validate(r) for r in rows], since=since)


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


async def workout_detail(
    session: AsyncSession, user: User, workout_id: int
) -> WorkoutDetail | None:
    """1 件の詳細。心拍の推移と、設定の境目がそろっていれば強度ごとの時間。他人の id は None。"""
    row = await get_workout(session, user.id, workout_id)
    if row is None:
        return None
    samples = await heart_rates(session, row.id)
    zones = zone_times(
        [s.avg_bpm for s in samples], row.duration_sec, user.zone_boundary_1, user.zone_boundary_2
    )
    return WorkoutDetail(
        **WorkoutSummary.model_validate(row).model_dump(),
        heart_rates=[HeartRateSample.model_validate(s) for s in samples],
        zones=zone_seconds(zones),
    )
