import asyncio
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.domain.apple_health import is_apple_watch, sport_of
from app.models import User, Vo2maxReading, Workout, WorkoutHeartRate
from app.schemas.ingest import IngestPayload
from app.services.ingest import ingest
from tests.factories import UserFactory

# Apple Watch と Google Health のサイクリングが 1 件ずつ入った、Health Auto Export の実データ
SAMPLE = Path(__file__).parent / "fixtures" / "sample_health-auto-export_workouts-v2.json"
APPLE_WATCH_ID = "EC706163-46F5-4250-916B-3909437C8064"


def _workouts_payload() -> IngestPayload:
    return IngestPayload.model_validate(json.loads(SAMPLE.read_text()))


def _vo2max_payload(*points: tuple[str, float, str | None]) -> IngestPayload:
    data = [{"date": date, "qty": qty, "source": source} for date, qty, source in points]
    return IngestPayload.model_validate(
        {"data": {"metrics": [{"name": "vo2_max", "units": "ml/(kg·min)", "data": data}]}}
    )


async def _count(
    session: AsyncSession, model: type[Workout | WorkoutHeartRate | Vo2maxReading]
) -> int:
    return await session.scalar(select(func.count()).select_from(model)) or 0


async def test_takes_only_apple_watch_workouts(session: AsyncSession) -> None:
    user = await UserFactory.create_async()

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
    user = await UserFactory.create_async()
    await ingest(session, user.id, _workouts_payload())

    result = await ingest(session, user.id, _workouts_payload())

    assert (result.workouts_added, result.workouts_updated) == (0, 1)
    assert await _count(session, Workout) == 1
    assert await _count(session, WorkoutHeartRate) == 72


async def test_same_workout_sent_at_once_is_not_doubled(engine: AsyncEngine) -> None:
    """同じ記録が 2 本同時に届いても、1 件と心拍 72 件のまま。users の行のロックで直列にする。

    session fixture は 1 本の接続を巻き戻す作りで同時実行を再現できないので、
    ここだけ接続を 2 本張って本当に commit し、終わりに利用者ごと消す。
    """
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        user = UserFactory.build()
        s.add(user)
        await s.commit()
        user_id = user.id

    async def send() -> tuple[int, int]:
        async with factory() as s:
            result = await ingest(s, user_id, _workouts_payload())
            return result.workouts_added, result.workouts_updated

    try:
        # 新規の競合: 片方が作り、もう片方は上書きになる（一意制約で落ちない）
        results = await asyncio.gather(send(), send())
        assert sorted(results) == [(0, 1), (1, 0)]

        # 既存の競合: 心拍の入れ替えが重なっても二重にならない
        await asyncio.gather(send(), send())

        async with factory() as s:
            workouts = await s.scalar(
                select(func.count()).select_from(Workout).where(Workout.user_id == user_id)
            )
            heart_rates = await s.scalar(
                select(func.count())
                .select_from(WorkoutHeartRate)
                .join(Workout)
                .where(Workout.user_id == user_id)
            )
        assert (workouts, heart_rates) == (1, 72)
    finally:
        async with factory() as s:
            await s.execute(delete(User).where(User.id == user_id))
            await s.commit()


async def test_vo2max_takes_apple_watch_and_skips_duplicates(session: AsyncSession) -> None:
    user = await UserFactory.create_async()
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


async def test_vo2max_from_other_sources_only_adds_nothing(session: AsyncSession) -> None:
    user = await UserFactory.create_async()

    result = await ingest(
        session,
        user.id,
        _vo2max_payload(
            ("2026-09-13 08:00:00 +0900", 45.0, "Google Health"),
            ("2026-09-14 08:00:00 +0900", 46.0, None),
        ),
    )

    assert (result.vo2max_added, result.vo2max_skipped) == (0, 2)
    assert await _count(session, Vo2maxReading) == 0


async def test_metrics_other_than_vo2max_are_ignored(session: AsyncSession) -> None:
    user = await UserFactory.create_async()
    payload = IngestPayload.model_validate(
        {
            "data": {
                "metrics": [
                    {
                        "name": "resting_heart_rate",
                        "data": [
                            {
                                "date": "2026-09-13 08:00:00 +0900",
                                "qty": 52,
                                "source": "Apple Watch",
                            }
                        ],
                    }
                ]
            }
        }
    )

    result = await ingest(session, user.id, payload)

    assert result.model_dump() == {
        "workouts_added": 0,
        "workouts_updated": 0,
        "workouts_skipped": 0,
        "vo2max_added": 0,
        "vo2max_updated": 0,
        "vo2max_skipped": 0,
    }
    assert await _count(session, Vo2maxReading) == 0


async def test_vo2max_resent_with_a_new_value_is_updated(session: AsyncSession) -> None:
    user = await UserFactory.create_async()
    at = "2026-07-05 21:21:11 +0900"
    await ingest(session, user.id, _vo2max_payload((at, 46.5, "Apple\xa0Watch")))

    result = await ingest(session, user.id, _vo2max_payload((at, 47.04, "Apple\xa0Watch")))

    assert (result.vo2max_added, result.vo2max_updated, result.vo2max_skipped) == (0, 1, 0)
    assert list(await session.scalars(select(Vo2maxReading.value))) == [Decimal("47.0")]


async def test_vo2max_later_point_wins_within_one_payload(session: AsyncSession) -> None:
    user = await UserFactory.create_async()
    at = "2026-07-05 21:21:11 +0900"

    result = await ingest(
        session,
        user.id,
        _vo2max_payload((at, 46.5, "Apple\xa0Watch"), (at, 47.0, "Apple\xa0Watch")),
    )

    assert (result.vo2max_added, result.vo2max_updated, result.vo2max_skipped) == (1, 1, 0)
    assert list(await session.scalars(select(Vo2maxReading.value))) == [Decimal("47.0")]


@pytest.mark.parametrize(
    ("name", "sport"),
    [
        # Health Auto Export の実データに出てくる種目名
        ("屋外 サイクリング", "ride"),
        ("屋内 サイクリング", "ride"),
        ("屋外 ラン", "run"),
        ("屋内 ラン", "run"),
        ("Outdoor Cycling", "ride"),
        ("Outdoor Run", "run"),
        ("Running", "run"),
        ("屋外 歩く", None),
        ("歩く", None),
        ("ゴルフ", None),
    ],
)
def test_sport_of(name: str, sport: str | None) -> None:
    assert sport_of(name) == sport


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("Apple\xa0Watch", True),
        # 名前を付けた時計。VO2max では 2 つの名前が「|」でつながって届く
        ("TaketoshiのApple\xa0Watch", True),
        ("Apple\xa0Watch | TaketoshiのApple\xa0Watch", True),
        ("Google Health", False),
        ("フィットネス", False),
        (None, False),
    ],
)
def test_is_apple_watch(source: str | None, expected: bool) -> None:
    assert is_apple_watch(source) is expected


async def test_run_from_named_watch_is_taken(session: AsyncSession) -> None:
    user = await UserFactory.create_async()
    payload = IngestPayload.model_validate(
        {
            "data": {
                "workouts": [
                    {
                        "id": "run-1",
                        "name": "屋外 ラン",
                        "start": "2026-10-04 07:00:00 +0900",
                        "end": "2026-10-04 07:30:00 +0900",
                        "duration": 1800,
                        "source": {"name": "TaketoshiのApple\xa0Watch"},
                    }
                ]
            }
        }
    )

    result = await ingest(session, user.id, payload)

    assert result.workouts_added == 1
    workout = await session.scalar(select(Workout))
    assert workout is not None
    assert workout.sport == "run"


async def test_other_sports_are_skipped(session: AsyncSession) -> None:
    user = await UserFactory.create_async()
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


async def test_same_record_twice_in_one_payload(session: AsyncSession) -> None:
    """1 回の中に同じ記録が 2 度あれば、後のほうで上書きし、心拍も後のほうだけ残す。"""
    user = await UserFactory.create_async()
    first, second = (
        {
            "id": "ride-1",
            "name": "屋外 サイクリング",
            "start": "2026-10-04 07:00:00 +0900",
            "end": "2026-10-04 07:30:00 +0900",
            "duration": duration,
            "source": {"name": "Apple\xa0Watch"},
            "heartRateData": [
                {"date": "2026-10-04 07:00:00 +0900", "Min": bpm, "Avg": bpm, "Max": bpm}
            ],
        }
        for duration, bpm in [(1800, 120), (1500, 130)]
    )
    vo2max = {"date": "2026-10-04 08:00:00 +0900", "qty": 45.0, "source": "Apple\xa0Watch"}
    payload = IngestPayload.model_validate(
        {
            "data": {
                "workouts": [first, second],
                "metrics": [{"name": "vo2_max", "data": [vo2max, vo2max]}],
            }
        }
    )

    result = await ingest(session, user.id, payload)

    assert (result.workouts_added, result.workouts_updated) == (1, 1)
    assert (result.vo2max_added, result.vo2max_skipped) == (1, 1)
    workout = await session.scalar(select(Workout))
    assert workout is not None
    assert workout.duration_sec == 1500
    assert list(await session.scalars(select(WorkoutHeartRate.avg_bpm))) == [130]
    assert await _count(session, Vo2maxReading) == 1
