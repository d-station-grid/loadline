import re
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User, Vo2maxReading, Workout, WorkoutHeartRate
from app.schemas.ingest import IngestPayload, IngestResult, MetricIn, WorkoutIn

APPLE_WATCH = "Apple Watch"
_SPACES = re.compile(r"\s+")

# 種目名（日本語と英語）に含まれる語から loadline の sport へ。ここにない種目は取り込まない。
# Health Auto Export の種目名は「屋外 ラン」「Outdoor Run」のように短いので、
# 「ラン」「Run」で見る（「ランニング」「Running」もこれで当たる）
_SPORTS = {
    "サイクリング": "ride",
    "Cycling": "ride",
    "ラン": "run",
    "Run": "run",
}


def is_apple_watch(source: str | None) -> bool:
    """source が Apple Watch か。空白に \\xa0 が混ざるので、正規化してから比べる。

    時計に名前を付けると「TaketoshiのApple Watch」、VO2max では
    「Apple Watch | TaketoshiのApple Watch」のように届くので、含まれているかで見る。
    """
    if source is None:
        return False
    return APPLE_WATCH in _SPACES.sub(" ", source)


def parse_time(value: str) -> datetime:
    """ "2026-09-13 14:10:45 +0900" を tz 付きの datetime にする。"""
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S %z")


def sport_of(name: str) -> str | None:
    """種目名に含まれる語から ride か run を決める。どちらでもなければ None。"""
    for word, sport in _SPORTS.items():
        if word in name:
            return sport
    return None


def _bpm(value: float | None) -> int | None:
    return None if value is None else round(value)


async def _upsert_workout(
    session: AsyncSession, user_id: int, w: WorkoutIn, result: IngestResult
) -> None:
    sport = sport_of(w.name)
    if not is_apple_watch(w.source.name) or sport is None:
        result.workouts_skipped += 1
        return

    row = await session.scalar(
        select(Workout).where(Workout.user_id == user_id, Workout.external_id == w.id)
    )
    if row is None:
        row = Workout(user_id=user_id, external_id=w.id)
        session.add(row)
        result.workouts_added += 1
    else:
        # 同じ記録が届き直したら、値を上書きし、心拍は入れ替える
        await session.execute(delete(WorkoutHeartRate).where(WorkoutHeartRate.workout_id == row.id))
        result.workouts_updated += 1

    row.sport = sport
    row.started_at = parse_time(w.start)
    row.ended_at = parse_time(w.end)
    row.duration_sec = round(w.duration)
    row.avg_heart_rate = _bpm(w.avg_heart_rate.qty if w.avg_heart_rate else None)
    row.max_heart_rate = _bpm(w.max_heart_rate.qty if w.max_heart_rate else None)
    await session.flush()

    session.add_all(
        WorkoutHeartRate(
            workout_id=row.id,
            recorded_at=parse_time(p.date),
            min_bpm=round(p.min_bpm),
            avg_bpm=round(p.avg_bpm),
            max_bpm=round(p.max_bpm),
        )
        for p in w.heart_rate_data
    )


async def _insert_vo2max(
    session: AsyncSession, user_id: int, metric: MetricIn, result: IngestResult
) -> None:
    for p in metric.data:
        if not is_apple_watch(p.source):
            result.vo2max_skipped += 1
            continue
        measured_at = parse_time(p.date)
        exists = await session.scalar(
            select(Vo2maxReading.id).where(
                Vo2maxReading.user_id == user_id, Vo2maxReading.measured_at == measured_at
            )
        )
        if exists is not None:
            result.vo2max_skipped += 1
            continue
        value = Decimal(str(p.qty)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
        session.add(Vo2maxReading(user_id=user_id, measured_at=measured_at, value=value))
        result.vo2max_added += 1


async def ingest(session: AsyncSession, user_id: int, payload: IngestPayload) -> IngestResult:
    """Health Auto Export から届いた 1 回分を取り込む。workouts と metrics のどちらが来てもよい。"""
    result = IngestResult()
    # 同じ利用者の取り込みを直列にする。同じ記録が 2 本同時に届くと、心拍の入れ替えが
    # 重なって二重になり、新規の記録は一意制約で片方が落ちるため
    await session.execute(select(User.id).where(User.id == user_id).with_for_update())
    for w in payload.data.workouts:
        await _upsert_workout(session, user_id, w, result)
    for metric in payload.data.metrics:
        if metric.name == "vo2_max":
            await _insert_vo2max(session, user_id, metric, result)
    await session.commit()
    return result
