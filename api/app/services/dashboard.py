from collections import defaultdict
from dataclasses import asdict
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.load import FITNESS_DAYS, WorkoutLoad, daily_loads, fitness_fatigue, workout_load
from app.domain.vo2max import AVERAGE_DAYS, vo2max_trend
from app.models import User, Vo2maxReading, Workout, WorkoutHeartRate
from app.schemas.dashboard import Dashboard, DayPoint, Sport, Vo2maxPoint, WorkoutPoint
from app.schemas.workouts import ZoneSeconds

# 表示の期間より前から計算を始める日数。体力の時定数の 6 倍で、それより前の負荷は
# e^(−6) ≈ 0.25% しか残らない。0 から立ち上がって期間の初日の体力が低く出るのを防ぐ
WARMUP_DAYS = 6 * FITNESS_DAYS

# 受け付ける最も古い日付。Apple Watch の記録はこれより後で、上の日数を引いても
# date の範囲（0001-01-01 から）からあふれない。until は今日で切るので上の端は要らない
EARLIEST_DAY = date(2000, 1, 1)


class InvalidPeriodError(ValueError):
    """since が until より後か、受け付ける範囲の外。field はどのクエリが悪いか。"""

    def __init__(self, field: str, value: date, message: str) -> None:
        super().__init__(message)
        self.field = field
        self.value = value


def _start_of(day: date, tz: ZoneInfo) -> datetime:
    """利用者のタイムゾーンでのその日の 0 時。"""
    return datetime.combine(day, time.min, tzinfo=tz)


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


def _sum_zones(loads: list[WorkoutLoad]) -> ZoneSeconds | None:
    """期間の強度ごとの時間の合計。境目がそろっている前提で呼ぶ。

    心拍のないワークアウトが 1 件でもあれば None（分からない）。外して足すと、全部が
    心拍なしのとき 0 秒に見えるため。日ごとの負荷と同じ扱い。ワークアウトが 0 件なら 0 秒。
    """
    known = [w.zones for w in loads if w.zones is not None]
    if len(known) < len(loads):
        return None
    return ZoneSeconds(
        low=sum(z.low for z in known),
        mid=sum(z.mid for z in known),
        high=sum(z.high for z in known),
    )


async def _vo2max(
    session: AsyncSession, user_id: int, since: date, until: date, tz: ZoneInfo
) -> list[Vo2maxPoint]:
    """期間の測定と 30 日平均。平均のために、期間の前 29 日の測定も読む。"""
    stmt = (
        select(Vo2maxReading.measured_at, Vo2maxReading.value)
        .where(
            Vo2maxReading.user_id == user_id,
            Vo2maxReading.measured_at >= _start_of(since - timedelta(days=AVERAGE_DAYS - 1), tz),
            Vo2maxReading.measured_at < _start_of(until + timedelta(days=1), tz),
        )
        .order_by(Vo2maxReading.measured_at)
    )
    readings = [(at.astimezone(tz).date(), float(v)) for at, v in await session.execute(stmt)]
    return [Vo2maxPoint(**asdict(p)) for p in vo2max_trend(readings) if p.day >= since]


async def build_dashboard(
    session: AsyncSession, user: User, since: date | None, until: date | None, sport: Sport
) -> Dashboard:
    """期間（両端を含む）のダッシュボード。since がなければ最初のワークアウトの日から、
    until がなければ今日まで。保存はせず、呼ばれるたびに計算する。

    until は今日で切る。未来の日を負荷 0 で埋めると、体力と疲労が先まで減っていく線が
    予測のように見えるため。期間の検査は既定値を決めて切った後にする。until を省いて
    since に未来の日を渡すと、決める前の検査では逆転を見逃すため。
    """
    tz = ZoneInfo(user.timezone)
    today = datetime.now(tz).date()
    until = min(until or today, today)
    if since is None:
        since = min(await _first_day(session, user.id, tz) or until, until)
    if since < EARLIEST_DAY:
        raise InvalidPeriodError("since", since, f"since must be on or after {EARLIEST_DAY}")
    if since > until:
        raise InvalidPeriodError(
            "since", since, f"since must be on or before until ({until}, capped at today)"
        )

    warm_start = since - timedelta(days=WARMUP_DAYS)
    rows = await _workouts(
        session, user.id, _start_of(warm_start, tz), _start_of(until + timedelta(days=1), tz)
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
        zones=_sum_zones([wl for _, _, wl in picked]) if has_boundaries else None,
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
