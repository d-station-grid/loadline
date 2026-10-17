"""件数を増やしても、DB への問い合わせの数が変わらないこと（N+1 がないこと）を確かめる。

どのテストも、記録が 1 件のときに数え、50 件に増やしてもう一度数えて比べる。
"""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Identity, InvalidTokenError, get_token_verifier
from app.main import app
from app.models import User, Workout
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
