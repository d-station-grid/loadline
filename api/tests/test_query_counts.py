"""件数を増やしても、DB への問い合わせの数が変わらないこと（N+1 がないこと）を確かめる。

どのテストも、記録が 1 件のときに数え、50 件に増やしてもう一度数えて比べる。
"""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Identity, InvalidTokenError, get_token_verifier
from app.main import app
from app.models import User, Workout
from app.services.ingest_tokens import issue_token
from tests.conftest import QueryCounter
from tests.factories import (
    UserFactory,
    Vo2maxReadingFactory,
    WorkoutFactory,
    WorkoutHeartRateFactory,
)

HEADERS = {"Authorization": "Bearer good"}
START = datetime(2026, 9, 1, 6, 0, tzinfo=UTC)
MANY = 50


class FakeVerifier:
    def verify(self, token: str) -> Identity:
        if token == "good":
            return Identity(uid="uid-1", email="one@example.com")
        raise InvalidTokenError


@pytest.fixture(autouse=True)
def fake_verifier() -> Iterator[None]:
    app.dependency_overrides[get_token_verifier] = FakeVerifier
    yield
    app.dependency_overrides.pop(get_token_verifier, None)


async def _me() -> User:
    """ログインする本人。負荷と強度の計算まで通るよう、心拍の設定をそろえる。"""
    return await UserFactory.create_async(
        firebase_uid="uid-1",
        max_heart_rate=177,
        resting_heart_rate=75,
        zone_boundary_1=130,
        zone_boundary_2=155,
    )


async def _add_workouts(user: User, days: range) -> None:
    """その日ごとのワークアウトと 1 分ごとの心拍 3 件、VO2max 1 件。"""
    for day in days:
        started_at = START + timedelta(days=day)
        workout = await WorkoutFactory.create_async(user_id=user.id, started_at=started_at)
        await WorkoutHeartRateFactory.create_batch_async(3, workout_id=workout.id)
        await Vo2maxReadingFactory.create_async(user_id=user.id, measured_at=started_at)


async def _count_get(client: AsyncClient, queries: QueryCounter, url: str) -> list[str]:
    queries.reset()
    res = await client.get(url, headers=HEADERS)
    assert res.status_code == 200
    return list(queries.statements)


@pytest.mark.parametrize("url", ["/workouts", "/dashboard?until=2026-12-31"])
async def test_list_and_dashboard(
    client: AsyncClient, session: AsyncSession, queries: QueryCounter, url: str
) -> None:
    me = await _me()
    await _add_workouts(me, range(1))
    one = await _count_get(client, queries, url)

    await _add_workouts(me, range(1, MANY))
    many = await _count_get(client, queries, url)

    assert len(many) == len(one), many


async def test_workout_detail(
    client: AsyncClient, session: AsyncSession, queries: QueryCounter
) -> None:
    """詳細は、心拍のサンプルを 1 件から 50 件に増やして比べる。"""
    me = await _me()
    workout: Workout = await WorkoutFactory.create_async(user_id=me.id)
    url = f"/workouts/{workout.id}"
    await WorkoutHeartRateFactory.create_async(workout_id=workout.id)
    one = await _count_get(client, queries, url)

    await WorkoutHeartRateFactory.create_batch_async(MANY - 1, workout_id=workout.id)
    many = await _count_get(client, queries, url)

    assert len(many) == len(one), many


def _payload(days: range, duration: int = 1800) -> dict[str, Any]:
    """Health Auto Export の形で、その日ごとのワークアウト（心拍 3 件）と VO2max。"""
    workouts = []
    vo2max = []
    for day in days:
        start = START + timedelta(days=day)
        workouts.append(
            {
                "id": f"workout-{day}",
                "name": "屋外 サイクリング",
                "start": f"{start:%Y-%m-%d %H:%M:%S %z}",
                "end": f"{start + timedelta(seconds=duration):%Y-%m-%d %H:%M:%S %z}",
                "duration": duration,
                "source": {"name": "Apple\xa0Watch"},
                "heartRateData": [
                    {
                        "date": f"{start + timedelta(minutes=m):%Y-%m-%d %H:%M:%S %z}",
                        "Min": 115,
                        "Avg": 120,
                        "Max": 125,
                    }
                    for m in range(3)
                ],
            }
        )
        vo2max.append(
            {"date": f"{start:%Y-%m-%d %H:%M:%S %z}", "qty": 45.0, "source": "Apple\xa0Watch"}
        )
    return {
        "data": {
            "workouts": workouts,
            "metrics": [{"name": "vo2_max", "units": "ml/(kg·min)", "data": vo2max}],
        }
    }


async def _count_ingest(
    client: AsyncClient, queries: QueryCounter, token: str, body: dict[str, Any]
) -> list[str]:
    queries.reset()
    res = await client.post("/ingest", json=body, headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    return list(queries.statements)


async def test_ingest_new_records(
    client: AsyncClient, session: AsyncSession, queries: QueryCounter
) -> None:
    token, _ = await issue_token(session, (await _me()).id)

    one = await _count_ingest(client, queries, token, _payload(range(1)))
    many = await _count_ingest(client, queries, token, _payload(range(1, 1 + MANY)))

    assert len(many) == len(one), many


async def test_ingest_sent_again(
    client: AsyncClient, session: AsyncSession, queries: QueryCounter
) -> None:
    """値を変えて届き直すと、ワークアウトは上書き、心拍は入れ替え、VO2max は飛ばす。"""
    token, _ = await issue_token(session, (await _me()).id)
    await _count_ingest(client, queries, token, _payload(range(MANY)))

    one = await _count_ingest(client, queries, token, _payload(range(1), duration=1500))
    many = await _count_ingest(client, queries, token, _payload(range(MANY), duration=1200))

    assert len(many) == len(one), many
    assert any(s.startswith("UPDATE workouts") for s in many)
