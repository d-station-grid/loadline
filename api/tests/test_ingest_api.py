import json
from pathlib import Path

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.services.ingest_tokens import current_token, issue_token

SAMPLE = (
    Path(__file__).resolve().parents[2] / "notes" / "sample_health-auto-export_workouts-v2.json"
)


async def _user_with_token(session: AsyncSession) -> tuple[User, str]:
    user = User(firebase_uid="uid-1", email="one@example.com")
    session.add(user)
    await session.flush()
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
