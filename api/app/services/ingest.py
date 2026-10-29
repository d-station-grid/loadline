from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.apple_health import bpm, is_apple_watch, parse_time, sport_of, vo2max_value
from app.models import User, Vo2maxReading, Workout, WorkoutHeartRate
from app.schemas.ingest import IngestPayload, IngestResult, MetricIn, WorkoutIn

# 届き直したときに上書きする列
_COLUMNS = (
    "sport",
    "started_at",
    "ended_at",
    "duration_sec",
    "avg_heart_rate",
    "max_heart_rate",
)


async def _upsert_workouts(
    session: AsyncSession, user_id: int, workouts: list[WorkoutIn], result: IngestResult
) -> None:
    """ワークアウトをまとめて取り込む。件数が増えても問い合わせの数は変わらない。

    既にある行は 1 回でまとめて読み、心拍は 1 回で消して、まとめて入れ直す。
    同じ id が 1 回の中に 2 度あれば、後のものが勝つ（届き直しと同じ扱い）。
    """
    taken: list[tuple[WorkoutIn, str]] = []
    for w in workouts:
        sport = sport_of(w.name)
        if not is_apple_watch(w.source.name) or sport is None:
            result.workouts_skipped += 1
        else:
            taken.append((w, sport))
    if not taken:
        return

    # 前からある行は、id と上書きする列の値だけをまとめて読む。上書きは下でまとめて送る
    stored = await session.execute(
        select(Workout.external_id, Workout.id, *(getattr(Workout, c) for c in _COLUMNS)).where(
            Workout.user_id == user_id, Workout.external_id.in_({w.id for w, _ in taken})
        )
    )
    existing: dict[str, int] = {}
    before: dict[int, dict[str, Any]] = {}
    for external_id, workout_id, *columns in stored:
        existing[external_id] = workout_id
        before[workout_id] = dict(zip(_COLUMNS, columns, strict=True))
    # 届き直した記録の心拍は入れ替える。消すのは前からある行の分だけ
    if existing:
        await session.execute(
            delete(WorkoutHeartRate).where(WorkoutHeartRate.workout_id.in_(existing.values()))
        )

    added: dict[str, Workout] = {}
    updates: dict[int, dict[str, Any]] = {}
    heart_rates: dict[str, WorkoutIn] = {}
    for w, sport in taken:
        values: dict[str, Any] = {
            "sport": sport,
            "started_at": parse_time(w.start),
            "ended_at": parse_time(w.end),
            "duration_sec": round(w.duration),
            "avg_heart_rate": bpm(w.avg_heart_rate.qty if w.avg_heart_rate else None),
            "max_heart_rate": bpm(w.max_heart_rate.qty if w.max_heart_rate else None),
        }
        if w.id in existing:
            workout_id = existing[w.id]
            # 値が同じなら UPDATE を送らない。updated_at を「値が変わった日時」に保つ
            if values == before[workout_id]:
                updates.pop(workout_id, None)
            else:
                updates[workout_id] = {"id": workout_id, **values}
            result.workouts_updated += 1
        elif w.id in added:
            for key, value in values.items():
                setattr(added[w.id], key, value)
            result.workouts_updated += 1
        else:
            added[w.id] = Workout(user_id=user_id, external_id=w.id, **values)
            session.add(added[w.id])
            result.workouts_added += 1
        heart_rates[w.id] = w
    if updates:
        # どの行も全部の列を渡す。変わった列が記録ごとに違っても、1 回の executemany で送れる
        await session.execute(update(Workout), list(updates.values()))
    # 新しい行の id を付ける
    await session.flush()
    ids = existing | {external_id: row.id for external_id, row in added.items()}

    samples = [
        {
            "workout_id": ids[external_id],
            "recorded_at": parse_time(p.date),
            "min_bpm": round(p.min_bpm),
            "avg_bpm": round(p.avg_bpm),
            "max_bpm": round(p.max_bpm),
        }
        for external_id, w in heart_rates.items()
        for p in w.heart_rate_data
    ]
    if samples:
        # 何千件あっても 1 回の executemany で送る
        await session.execute(insert(WorkoutHeartRate), samples)


async def _upsert_vo2max(
    session: AsyncSession, user_id: int, metric: MetricIn, result: IngestResult
) -> None:
    """VO2max をまとめて取り込む。同じ日時の測定が届き直したら、値が違うときだけ上書きする。

    同じ日時が 1 回の中に 2 度あれば、後のものが勝つ（ワークアウトと同じ扱い）。
    値が同じ届き直しは何も送らず、skipped に数える。
    """
    points: list[tuple[datetime, Decimal]] = []
    for p in metric.data:
        if is_apple_watch(p.source):
            points.append((parse_time(p.date), vo2max_value(p.qty)))
        else:
            result.vo2max_skipped += 1
    if not points:
        return

    stored = await session.execute(
        select(Vo2maxReading.measured_at, Vo2maxReading.id, Vo2maxReading.value).where(
            Vo2maxReading.user_id == user_id,
            Vo2maxReading.measured_at.in_({at for at, _ in points}),
        )
    )
    existing: dict[datetime, tuple[int, Decimal]] = {
        at: (reading_id, value) for at, reading_id, value in stored
    }
    added: dict[datetime, Vo2maxReading] = {}
    updates: dict[int, dict[str, Any]] = {}
    for measured_at, value in points:
        if measured_at in added:
            row = added[measured_at]
            if row.value == value:
                result.vo2max_skipped += 1
            else:
                row.value = value
                result.vo2max_updated += 1
        elif measured_at in existing:
            reading_id, before = existing[measured_at]
            if before == value:
                result.vo2max_skipped += 1
            else:
                updates[reading_id] = {"id": reading_id, "value": value}
                existing[measured_at] = (reading_id, value)
                result.vo2max_updated += 1
        else:
            added[measured_at] = Vo2maxReading(
                user_id=user_id, measured_at=measured_at, value=value
            )
            session.add(added[measured_at])
            result.vo2max_added += 1
    if updates:
        await session.execute(update(Vo2maxReading), list(updates.values()))


async def ingest(session: AsyncSession, user_id: int, payload: IngestPayload) -> IngestResult:
    """Health Auto Export から届いた 1 回分を取り込む。workouts と metrics のどちらが来てもよい。"""
    result = IngestResult()
    # 同じ利用者の取り込みを直列にする。同じ記録が 2 本同時に届くと、心拍の入れ替えが
    # 重なって二重になり、新規の記録は一意制約で片方が落ちるため
    await session.execute(select(User.id).where(User.id == user_id).with_for_update())
    await _upsert_workouts(session, user_id, payload.data.workouts, result)
    for metric in payload.data.metrics:
        if metric.name == "vo2_max":
            await _upsert_vo2max(session, user_id, metric, result)
    await session.commit()
    return result
