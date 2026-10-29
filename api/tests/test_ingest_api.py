import json
from pathlib import Path

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User, Workout
from app.services.ingest_tokens import current_token, issue_token
from tests.factories import UserFactory

SAMPLE = Path(__file__).parent / "fixtures" / "sample_health-auto-export_workouts-v2.json"


async def _user_with_token(session: AsyncSession) -> tuple[User, str]:
    user = await UserFactory.create_async()
    token, _ = await issue_token(session, user.id)
    return user, token


async def test_without_token_is_401(client: AsyncClient) -> None:
    res = await client.post("/ingest", json={"data": {"workouts": []}})

    assert res.status_code == 401
    assert res.headers["WWW-Authenticate"] == "Bearer"


async def test_wrong_token_is_401(client: AsyncClient, session: AsyncSession) -> None:
    await _user_with_token(session)

    res = await client.post(
        "/ingest",
        json={"data": {"workouts": []}},
        headers={"Authorization": "Bearer not-the-token"},
    )

    assert res.status_code == 401


async def test_valid_token_ingests_and_marks_last_used(
    client: AsyncClient, session: AsyncSession
) -> None:
    user, token = await _user_with_token(session)

    res = await client.post(
        "/ingest",
        json=json.loads(SAMPLE.read_text()),
        headers={"Authorization": f"Bearer {token}"},
    )

    assert res.status_code == 200
    assert res.json() == {
        "workouts_added": 1,
        "workouts_updated": 0,
        "workouts_skipped": 1,
        "vo2max_added": 0,
        "vo2max_updated": 0,
        "vo2max_skipped": 0,
    }
    row = await current_token(session, user.id)
    assert row is not None
    assert row.last_used_at is not None


async def test_malformed_body_is_422(client: AsyncClient, session: AsyncSession) -> None:
    _, token = await _user_with_token(session)

    res = await client.post(
        "/ingest", json={"workouts": []}, headers={"Authorization": f"Bearer {token}"}
    )

    assert res.status_code == 422


async def test_each_token_writes_only_to_its_owner(
    client: AsyncClient, session: AsyncSession
) -> None:
    """同じファイルを 2 人が送っても、それぞれの行に入る。A がもう一度送っても B は変わらない。"""
    a, token_a = await _user_with_token(session)
    b, token_b = await _user_with_token(session)
    body = json.loads(SAMPLE.read_text())

    for token in (token_a, token_b):
        res = await client.post("/ingest", json=body, headers={"Authorization": f"Bearer {token}"})
        assert res.json()["workouts_added"] == 1
    b_before = await session.scalar(select(Workout).where(Workout.user_id == b.id))
    assert b_before is not None
    b_updated_at = b_before.updated_at

    again = await client.post("/ingest", json=body, headers={"Authorization": f"Bearer {token_a}"})

    assert again.json()["workouts_updated"] == 1
    owners = await session.scalars(select(Workout.user_id).order_by(Workout.user_id))
    assert list(owners) == [a.id, b.id]
    b_after = await session.scalar(select(Workout).where(Workout.user_id == b.id))
    assert b_after is not None
    assert b_after.updated_at == b_updated_at
