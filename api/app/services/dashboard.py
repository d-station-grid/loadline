from collections import defaultdict
from dataclasses import asdict
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.calendar import start_of_day, today_in
from app.domain.load import (
    FITNESS_DAYS,
    daily_loads,
    fitness_fatigue,
    total_zones,
    workout_load,
)
from app.domain.period import dashboard_period, needs_first_day
from app.domain.vo2max import AVERAGE_DAYS, vo2max_trend
from app.models import User, Vo2maxReading, Workout, WorkoutHeartRate
from app.schemas.dashboard import Dashboard, DayPoint, Sport, Vo2maxPoint, WorkoutPoint
from app.schemas.workouts import zone_seconds

# 表示の期間より前から計算を始める日数。体力の時定数の 6 倍で、それより前の負荷は
# e^(−6) ≈ 0.25% しか残らない。0 から立ち上がって期間の初日の体力が低く出るのを防ぐ
WARMUP_DAYS = 6 * FITNESS_DAYS


async def _first_day(session: AsyncSession, user_id: int, tz: ZoneInfo) -> date | None:
    first = await session.scalar(
        select(func.min(Workout.started_at)).where(Workout.user_id == user_id)
    )
    return None if first is None else first.astimezone(tz).date()


async def _workouts(
    session: AsyncSession, user_id: int, start: datetime, end: datetime
) -> list[Workout]:
    stmt = (
        select(Workout)
        .where(Workout.user_id == user_id, Workout.started_at >= start, Workout.started_at < end)
        .order_by(Workout.started_at)
    )
    return list(await session.scalars(stmt))


async def _bpms(session: AsyncSession, workout_ids: list[int]) -> dict[int, list[float]]:
    """ワークアウトごとの 1 分ごとの平均心拍。1 回の問い合わせでまとめて読む。"""
    if not workout_ids:
        return {}
    stmt = (
        select(WorkoutHeartRate.workout_id, WorkoutHeartRate.avg_bpm)
        .where(WorkoutHeartRate.workout_id.in_(workout_ids))
        .order_by(WorkoutHeartRate.workout_id, WorkoutHeartRate.recorded_at)
    )
    by_workout: dict[int, list[float]] = defaultdict(list)
    for workout_id, bpm in await session.execute(stmt):
        by_workout[workout_id].append(bpm)
    return by_workout


async def _vo2max(
    session: AsyncSession, user_id: int, since: date, until: date, tz: ZoneInfo
) -> list[Vo2maxPoint]:
    """期間の測定と 30 日平均。平均のために、期間の前 29 日の測定も読む。"""
    stmt = (
        select(Vo2maxReading.measured_at, Vo2maxReading.value)
        .where(
            Vo2maxReading.user_id == user_id,
            Vo2maxReading.measured_at >= start_of_day(since - timedelta(days=AVERAGE_DAYS - 1), tz),
            Vo2maxReading.measured_at < start_of_day(until + timedelta(days=1), tz),
        )
        .order_by(Vo2maxReading.measured_at)
    )
    readings = [(at.astimezone(tz).date(), float(v)) for at, v in await session.execute(stmt)]
    return [Vo2maxPoint(**asdict(p)) for p in vo2max_trend(readings) if p.day >= since]


async def build_dashboard(
    session: AsyncSession,
    user: User,
    since: date | None,
    until: date | None,
    sport: Sport,
    weeks: int | None = None,
    today: date | None = None,
) -> Dashboard:
    """期間（両端を含む）のダッシュボード。since がなければ最初のワークアウトの日から、
    until がなければ今日まで。保存はせず、呼ばれるたびに計算する。

    期間の決め方と検査は domain の dashboard_period。weeks を渡すと、since は until の
    weeks 週前の日になる。「直近 N 週」の始まりを利用者のタイムゾーンの今日から決めるため。
    期間の誤りは InvalidPeriodError。

    today は利用者のタイムゾーンでの今日。省けば今の時刻から決める。振り返りの service が
    自分の決めた今日と同じ日で切るために渡す。
    """
    tz = ZoneInfo(user.timezone)
    today = today or today_in(tz)
    first_day = await _first_day(session, user.id, tz) if needs_first_day(since, weeks) else None
    since, until = dashboard_period(today, since, until, weeks, first_day)

    warm_start = since - timedelta(days=WARMUP_DAYS)
    rows = await _workouts(
        session, user.id, start_of_day(warm_start, tz), start_of_day(until + timedelta(days=1), tz)
    )
    bpms = await _bpms(session, [w.id for w in rows])
    loads = [
        (
            w,
            w.started_at.astimezone(tz).date(),
            workout_load(
                bpms.get(w.id, []),
                w.duration_sec,
                max_hr=user.max_heart_rate,
                resting_hr=user.resting_heart_rate,
                boundary_1=user.zone_boundary_1,
                boundary_2=user.zone_boundary_2,
            ),
        )
        for w in rows
    ]

    needs_settings = user.max_heart_rate is None or user.resting_heart_rate is None
    days: list[DayPoint] = []
    if not needs_settings:
        daily = daily_loads(((day, wl.load) for _, day, wl in loads), warm_start, until)
        days = [DayPoint(**asdict(p)) for p in fitness_fatigue(daily) if p.day >= since]

    picked = [
        (w, day, wl)
        for w, day, wl in loads
        if day >= since and (sport == "all" or w.sport == sport)
    ]
    has_boundaries = user.zone_boundary_1 is not None and user.zone_boundary_2 is not None
    return Dashboard(
        since=since,
        until=until,
        sport=sport,
        needs_heart_rate_settings=needs_settings,
        days=days,
        vo2max=await _vo2max(session, user.id, since, until, tz),
        zones=zone_seconds(total_zones([wl for _, _, wl in picked])) if has_boundaries else None,
        workouts=[
            WorkoutPoint(
                id=w.id,
                sport=w.sport,
                started_at=w.started_at,
                day=day,
                load=wl.load,
                high_sec=None if wl.zones is None else wl.zones.high,
            )
            for w, day, wl in picked
        ],
    )
