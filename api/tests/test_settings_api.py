from collections.abc import Iterator

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Identity, InvalidTokenError, get_token_verifier
from app.main import app
from app.services.ingest_tokens import find_user_id_by_token, issue_token
from tests.factories import UserFactory

HEADERS = {"Authorization": "Bearer good"}


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


async def test_read_returns_defaults_for_new_user(client: AsyncClient) -> None:
    res = await client.get("/settings", headers=HEADERS)

    assert res.status_code == 200
    assert res.json() == {
        "max_heart_rate": None,
        "resting_heart_rate": None,
        "zone_boundary_1": None,
        "zone_boundary_2": None,
        "timezone": "Asia/Tokyo",
        "review_weekday": 0,
        "send_notes_to_ai": True,
        "ingest_token_last_four": None,
    }


async def test_update_then_read_back(client: AsyncClient) -> None:
    body = {
        "max_heart_rate": 180,
        "resting_heart_rate": 50,
        "zone_boundary_1": 130,
        "zone_boundary_2": 155,
        "timezone": "Europe/London",
        "review_weekday": 6,
        "send_notes_to_ai": False,
    }

    put = await client.put("/settings", json=body, headers=HEADERS)
    get = await client.get("/settings", headers=HEADERS)

    assert put.status_code == 200
    assert get.json() == {**body, "ingest_token_last_four": None}


async def test_invalid_settings_are_422(client: AsyncClient) -> None:
    body = {"zone_boundary_1": 160, "zone_boundary_2": 150}

    res = await client.put("/settings", json=body, headers=HEADERS)

    assert res.status_code == 422


async def test_issue_and_reissue_ingest_token(client: AsyncClient) -> None:
    first = await client.post("/settings/ingest-token", headers=HEADERS)
    second = await client.post("/settings/ingest-token", headers=HEADERS)
    settings = await client.get("/settings", headers=HEADERS)

    assert first.status_code == 200
    assert first.json()["token"].endswith(first.json()["last_four"])
    assert first.json()["token"] != second.json()["token"]
    assert settings.json()["ingest_token_last_four"] == second.json()["last_four"]


async def test_settings_require_login(client: AsyncClient) -> None:
    res = await client.get("/settings")

    assert res.status_code == 401


async def test_update_does_not_touch_another_user(
    client: AsyncClient, session: AsyncSession
) -> None:
    other = await UserFactory.create_async(max_heart_rate=190, timezone="Europe/London")
    body = {
        "max_heart_rate": 177,
        "resting_heart_rate": 75,
        "zone_boundary_1": 130,
        "zone_boundary_2": 155,
        "timezone": "Asia/Tokyo",
        "review_weekday": 6,
        "send_notes_to_ai": False,
    }

    assert (await client.put("/settings", json=body, headers=HEADERS)).status_code == 200

    await session.refresh(other)
    assert (other.max_heart_rate, other.timezone, other.review_weekday) == (
        190,
        "Europe/London",
        0,
    )


async def test_reissue_does_not_revoke_another_users_token(
    client: AsyncClient, session: AsyncSession
) -> None:
    other = await UserFactory.create_async()
    other_token, _ = await issue_token(session, other.id)

    await client.post("/settings/ingest-token", headers=HEADERS)
    await client.post("/settings/ingest-token", headers=HEADERS)

    assert await find_user_id_by_token(session, other_token) == other.id
