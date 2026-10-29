import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Identity, InvalidTokenError, get_token_verifier
from app.domain.calendar import since_for_weeks
from app.main import app
from app.models import User, Workout
from app.schemas.ingest import IngestPayload
from app.services.ingest import ingest
from tests.factories import UserFactory, WorkoutFactory

HEADERS = {"Authorization": "Bearer good"}
SAMPLE = Path(__file__).parent / "fixtures" / "sample_health-auto-export_workouts-v2.json"


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


async def _user_with_sample(session: AsyncSession, uid: str = "uid-1", **settings: Any) -> User:
    """ログインする本人（uid-1）と同じ uid で行を作り、fixtures の実データを取り込む。"""
    user = await UserFactory.create_async(firebase_uid=uid, **settings)
    await ingest(session, user.id, IngestPayload.model_validate(json.loads(SAMPLE.read_text())))
    return user


async def test_list_returns_own_workouts_newest_first(
    client: AsyncClient, session: AsyncSession
) -> None:
    await _user_with_sample(session)

    res = await client.get("/workouts", headers=HEADERS)

    assert res.status_code == 200
    items = res.json()["items"]
    assert len(items) == 1
    assert items[0]["sport"] == "ride"
    assert items[0]["duration_sec"] == 4028


async def test_list_filters_by_period(client: AsyncClient, session: AsyncSession) -> None:
    await _user_with_sample(session)

    inside = await client.get(
        "/workouts", params={"since": "2026-09-13T00:00:00+09:00"}, headers=HEADERS
    )
    outside = await client.get(
        "/workouts", params={"until": "2026-09-13T00:00:00+09:00"}, headers=HEADERS
    )

    assert len(inside.json()["items"]) == 1
    assert len(outside.json()["items"]) == 0


async def test_next_page_keeps_workouts_with_the_same_start(
    client: AsyncClient, session: AsyncSession
) -> None:
    """開始時刻がそろった記録がページの境目にあっても、続きの取得から抜けない。"""
    user = await UserFactory.create_async(firebase_uid="uid-1")
    same = datetime(2026, 9, 13, 5, 0, tzinfo=UTC)
    await WorkoutFactory.create_batch_async(3, user_id=user.id, started_at=same)
    await WorkoutFactory.create_async(user_id=user.id, started_at=same - timedelta(days=1))

    first = (await client.get("/workouts", params={"limit": 2}, headers=HEADERS)).json()["items"]
    last = first[-1]
    rest = (
        await client.get(
            "/workouts",
            params={"until": last["started_at"], "before_id": last["id"], "limit": 2},
            headers=HEADERS,
        )
    ).json()["items"]

    ids = [w["id"] for w in first + rest]
    all_ids = list(await session.scalars(select(Workout.id).where(Workout.user_id == user.id)))
    assert sorted(ids) == sorted(all_ids)
    assert len(set(ids)) == 4
    # 同じ開始時刻の中は id の大きい順
    assert [w["id"] for w in first] == sorted([w["id"] for w in first], reverse=True)


async def test_before_id_without_until_is_422(client: AsyncClient, session: AsyncSession) -> None:
    await UserFactory.create_async(firebase_uid="uid-1")

    res = await client.get("/workouts", params={"before_id": 1}, headers=HEADERS)

    assert res.status_code == 422
    assert res.json()["detail"][0]["loc"] == ["query", "before_id"]


async def test_weeks_starts_at_midnight_in_user_timezone(
    client: AsyncClient, session: AsyncSession
) -> None:
    """「直近 1 週」の境目は、利用者のタイムゾーンでの 1 週前の 0 時。UTC+14 で確かめる。"""
    tz = ZoneInfo("Pacific/Kiritimati")
    user = await UserFactory.create_async(firebase_uid="uid-1", timezone=tz.key)
    today = datetime.now(tz).date()
    start = datetime.combine(today - timedelta(weeks=1), datetime.min.time(), tzinfo=tz)
    inside = await WorkoutFactory.create_async(user_id=user.id, started_at=start)
    await WorkoutFactory.create_async(user_id=user.id, started_at=start - timedelta(seconds=1))

    res = await client.get("/workouts", params={"weeks": 1}, headers=HEADERS)

    assert res.status_code == 200
    assert [w["id"] for w in res.json()["items"]] == [inside.id]
    # 続きはこの since で取る。weeks を渡し直すと、日付をまたいだときに始まりがずれる
    assert datetime.fromisoformat(res.json()["since"]) == start


async def test_list_returns_the_since_it_used(client: AsyncClient, session: AsyncSession) -> None:
    await UserFactory.create_async(firebase_uid="uid-1")
    given = "2026-09-13T00:00:00+09:00"

    with_since = await client.get("/workouts", params={"since": given}, headers=HEADERS)
    without = await client.get("/workouts", headers=HEADERS)

    assert datetime.fromisoformat(with_since.json()["since"]) == datetime.fromisoformat(given)
    assert without.json()["since"] is None


def test_since_for_weeks_uses_the_date_in_user_timezone() -> None:
    """UTC では 10/22 でも、UTC+14 では 10/23。始まりは 10/23 から数える。"""
    tz = ZoneInfo("Pacific/Kiritimati")
    now = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)

    assert since_for_weeks(4, tz, now) == datetime(2026, 9, 25, 0, 0, tzinfo=tz)


@pytest.mark.parametrize(
    "params", [{"weeks": 1, "since": "2026-09-13T00:00:00+09:00"}, {"weeks": 0}, {"weeks": 521}]
)
async def test_invalid_weeks_is_422(
    client: AsyncClient, session: AsyncSession, params: dict[str, Any]
) -> None:
    await UserFactory.create_async(firebase_uid="uid-1")

    res = await client.get("/workouts", params=params, headers=HEADERS)

    assert res.status_code == 422
    assert res.json()["detail"][0]["loc"] == ["query", "weeks"]


async def test_detail_has_heart_rates_and_zones(client: AsyncClient, session: AsyncSession) -> None:
    await _user_with_sample(session, zone_boundary_1=130, zone_boundary_2=155)
    workout_id = await session.scalar(select(Workout.id))

    res = await client.get(f"/workouts/{workout_id}", headers=HEADERS)

    assert res.status_code == 200
    body = res.json()
    assert len(body["heart_rates"]) == 72
    assert body["heart_rates"][0]["avg_bpm"] == 105
    # 強度ごとの時間の合計は、1 サンプル 60 秒の 4320 秒ではなく duration の 4028 秒
    assert body["zones"] == {"low": 2797, "mid": 1175, "high": 56}


async def test_detail_zones_are_null_without_boundaries(
    client: AsyncClient, session: AsyncSession
) -> None:
    await _user_with_sample(session)
    workout_id = await session.scalar(select(Workout.id))

    res = await client.get(f"/workouts/{workout_id}", headers=HEADERS)

    assert res.json()["zones"] is None


async def test_other_users_workout_is_404(client: AsyncClient, session: AsyncSession) -> None:
    await _user_with_sample(session, uid="someone-else")
    workout_id = await session.scalar(select(Workout.id))

    res = await client.get(f"/workouts/{workout_id}", headers=HEADERS)

    assert res.status_code == 404
