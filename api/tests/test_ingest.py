import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User, Vo2maxReading, Workout, WorkoutHeartRate
from app.schemas.ingest import IngestPayload
from app.services.ingest import ingest

# Apple Watch と Google Health のサイクリングが 1 件ずつ入った、Health Auto Export の実データ
SAMPLE = Path(__file__).parent / "fixtures" / "sample_health-auto-export_workouts-v2.json"
APPLE_WATCH_ID = "EC706163-46F5-4250-916B-3909437C8064"


def _workouts_payload() -> IngestPayload:
    return IngestPayload.model_validate(json.loads(SAMPLE.read_text()))


def _vo2max_payload(*points: tuple[str, float, str]) -> IngestPayload:
    data = [{"date": date, "qty": qty, "source": source} for date, qty, source in points]
    return IngestPayload.model_validate(
        {"data": {"metrics": [{"name": "vo2_max", "units": "ml/(kg·min)", "data": data}]}}
    )


async def _make_user(session: AsyncSession) -> User:
    user = User(firebase_uid="uid-1", email="one@example.com")
    session.add(user)
    await session.flush()
    return user


async def _count(
    session: AsyncSession, model: type[Workout | WorkoutHeartRate | Vo2maxReading]
) -> int:
    return await session.scalar(select(func.count()).select_from(model)) or 0


async def test_takes_only_apple_watch_workouts(session: AsyncSession) -> None:
    user = await _make_user(session)

    result = await ingest(session, user.id, _workouts_payload())

    assert (result.workouts_added, result.workouts_skipped) == (1, 1)
    workout = await session.scalar(select(Workout))
    assert workout is not None
    assert workout.external_id == APPLE_WATCH_ID
    assert workout.sport == "ride"
    # DB は UTC で返す。同じ瞬間かどうかで比べる
    assert workout.started_at == datetime(2026, 9, 13, 5, 10, 45, tzinfo=UTC)
    assert workout.duration_sec == 4028
    assert workout.avg_heart_rate == 126
    assert workout.max_heart_rate == 174
    assert await _count(session, WorkoutHeartRate) == 72


async def test_same_workout_twice_is_not_doubled(session: AsyncSession) -> None:
    user = await _make_user(session)
    await ingest(session, user.id, _workouts_payload())

    result = await ingest(session, user.id, _workouts_payload())

    assert (result.workouts_added, result.workouts_updated) == (0, 1)
    assert await _count(session, Workout) == 1
    assert await _count(session, WorkoutHeartRate) == 72


async def test_vo2max_takes_apple_watch_and_skips_duplicates(session: AsyncSession) -> None:
    user = await _make_user(session)
    payload = _vo2max_payload(
        ("2026-07-05 21:21:11 +0900", 46.5, "Apple\xa0Watch"),
        ("2026-07-13 22:43:55 +0900", 46.73, "Apple\xa0Watch"),
        ("2026-09-15 00:00:00 +0900", 45.0958, "Google Health"),
    )

    first = await ingest(session, user.id, payload)
    second = await ingest(session, user.id, payload)

    assert (first.vo2max_added, first.vo2max_skipped) == (2, 1)
    assert (second.vo2max_added, second.vo2max_skipped) == (0, 3)
    values = await session.scalars(select(Vo2maxReading.value).order_by(Vo2maxReading.measured_at))
    assert list(values) == [Decimal("46.5"), Decimal("46.7")]


async def test_other_sports_are_skipped(session: AsyncSession) -> None:
    user = await _make_user(session)
    payload = IngestPayload.model_validate(
        {
            "data": {
                "workouts": [
                    {
                        "id": "walk-1",
                        "name": "ウォーキング",
                        "start": "2026-09-13 08:00:00 +0900",
                        "end": "2026-09-13 08:30:00 +0900",
                        "duration": 1800,
                        "source": {"name": "Apple\xa0Watch"},
                    }
                ]
            }
        }
    )

    result = await ingest(session, user.id, payload)

    assert result.workouts_skipped == 1
    assert await _count(session, Workout) == 0
