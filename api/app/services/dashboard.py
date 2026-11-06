from collections import defaultdict
from dataclasses import asdict
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.calendar import start_of_day
from app.domain.load import (
    FITNESS_DAYS,
    daily_loads,
    fitness_fatigue,
    total_zones,
    workout_load,
)
from app.domain.period import dashboard_period
from app.domain.situation import judge_form
from app.domain.summary import (
    CHANGE_DAYS,
    WorkoutItem,
    fitness_change,
    previous_period,
    totals,
    vo2max_baseline_before,
    weekly_zones,
)
from app.domain.vo2max import AVERAGE_DAYS, vo2max_trend
from app.models import User, Vo2maxReading, Workout, WorkoutHeartRate
from app.schemas.dashboard import (
    Changes,
    Dashboard,
    DayPoint,
    Sport,
    Totals,
    Vo2maxPoint,
    WorkoutPoint,
    ZoneWeek,
)
from app.schemas.workouts import ZoneSeconds, zone_seconds
from app.services.users import today_of

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


async def _vo2max_change(
    session: AsyncSession, user_id: int, latest: Vo2maxPoint | None, until: date, tz: ZoneInfo
) -> float | None:
    """期間の最新の測定と、その 28 日前かそれより前の最後の測定との差。どちらかなければ None。

    期間に測定がなくても読む。読む回数が記録の中身で変わらないようにするため。
    """
    before = vo2max_baseline_before(until if latest is None else latest.day)
    value = await session.scalar(
        select(Vo2maxReading.value)
        .where(
            Vo2maxReading.user_id == user_id,
            Vo2maxReading.measured_at < start_of_day(before + timedelta(days=1), tz),
        )
        .order_by(Vo2maxReading.measured_at.desc())
        .limit(1)
    )
    return None if latest is None or value is None else latest.value - float(value)


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

    期間の決め方と検査は domain の dashboard_period。weeks を渡すと、期間は until までの
    ちょうど weeks × 7 日になる。「直近 N 週」の始まりを利用者のタイムゾーンの今日から決めるため。
    期間の誤りは InvalidPeriodError。

    today は利用者のタイムゾーンでの今日。振り返りの service が自分の決めた今日と同じ日で
    切るために渡す。省けば today_of で決める（ふだんは今の日付、デモの利用者は最後の
    ワークアウトの日）。
    """
    tz = ZoneInfo(user.timezone)
    today = today or await today_of(session, user)
    # 期間を決めるほか、余力の区分（記録が 42 日に満たないか）にも使う
    first_day = await _first_day(session, user.id, tz)
    since, until = dashboard_period(today, since, until, weeks, first_day)
    previous_since, previous_until = previous_period(since, until)

    warm_start = since - timedelta(days=WARMUP_DAYS)
    # 前の期間の合計のため、期間が長いとウォームアップより前からも読む
    rows = await _workouts(
        session,
        user.id,
        start_of_day(min(warm_start, previous_since), tz),
        start_of_day(until + timedelta(days=1), tz),
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
    change = None
    form = None
    if not needs_settings:
        daily = daily_loads(((day, wl.load) for _, day, wl in loads), warm_start, until)
        points = fitness_fatigue(daily)
        days = [DayPoint(**asdict(p)) for p in points if p.day >= since]
        change = fitness_change(points, until)
        # 負荷が分からない日は、週の判定と同じく until までの 7 日で数える
        week_start = until - timedelta(days=CHANGE_DAYS - 1)
        unknown_days = sum(1 for p in points if p.day >= week_start and p.load is None)
        form = judge_form(points[-1], first_day, unknown_days)

    vo2max = await _vo2max(session, user.id, since, until, tz)
    items = [
        WorkoutItem(day=day, duration_sec=w.duration_sec, load=wl)
        for w, day, wl in loads
        if sport == "all" or w.sport == sport
    ]
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
        vo2max=vo2max,
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
        changes=Changes(
            fitness=None if change is None else change.fitness,
            fatigue=None if change is None else change.fatigue,
            headroom=None if change is None else change.headroom,
            vo2max=await _vo2max_change(
                session, user.id, vo2max[-1] if vo2max else None, until, tz
            ),
        ),
        form=form,
        zone_weeks=[
            ZoneWeek(
                start=week.start,
                end=week.end,
                zones=ZoneSeconds(**asdict(week.zones)),
                workouts_without_zones=week.workouts_without_zones,
            )
            for week in weekly_zones(items, since, until)
        ]
        if has_boundaries
        else None,
        totals=Totals(**asdict(totals(items, since, until))),
        previous_totals=Totals(**asdict(totals(items, previous_since, previous_until))),
        last_received_at=user.last_ingested_at,
    )
