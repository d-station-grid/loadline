import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Identity, InvalidTokenError, get_token_verifier
from app.main import app
from app.models import User, Workout, WorkoutHeartRate
from app.schemas.ingest import IngestPayload
from app.services.ingest import ingest
from app.services.workouts import zone_seconds

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


async def _user_with_sample(session: AsyncSession, uid: str = "uid-1") -> User:
    """ログインする本人（uid-1）と同じ uid で行を作り、fixtures の実データを取り込む。"""
    user = User(firebase_uid=uid, email=f"{uid}@example.com")
    session.add(user)
    await session.flush()
    await ingest(session, user.id, IngestPayload.model_validate(json.loads(SAMPLE.read_text())))
    return user


def _hr(avg: int) -> WorkoutHeartRate:
    return WorkoutHeartRate(workout_id=0, recorded_at=None, min_bpm=avg, avg_bpm=avg, max_bpm=avg)


def test_zone_seconds_splits_by_boundaries() -> None:
    samples = [_hr(100), _hr(129), _hr(130), _hr(154), _hr(155), _hr(170)]

    zones = zone_seconds(samples, 130, 155)

    assert zones is not None
    assert (zones.low, zones.mid, zones.high) == (120, 120, 120)


def test_zone_seconds_is_none_without_boundaries() -> None:
    assert zone_seconds([_hr(100)], None, 155) is None
    assert zone_seconds([_hr(100)], 130, None) is None


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


async def test_detail_has_heart_rates_and_zones(client: AsyncClient, session: AsyncSession) -> None:
    user = await _user_with_sample(session)
    user.zone_boundary_1 = 130
    user.zone_boundary_2 = 155
    await session.commit()
    workout_id = await session.scalar(select(Workout.id))

    res = await client.get(f"/workouts/{workout_id}", headers=HEADERS)

    assert res.status_code == 200
    body = res.json()
    assert len(body["heart_rates"]) == 72
    assert body["heart_rates"][0]["avg_bpm"] == 105
    zones = body["zones"]
    assert zones["low"] + zones["mid"] + zones["high"] == 72 * 60


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
