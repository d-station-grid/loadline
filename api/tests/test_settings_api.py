from collections.abc import Iterator
from datetime import datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Identity, InvalidTokenError, get_token_verifier
from app.main import app
from app.models import User
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
        "language": "en",
        "ingest_token_last_four": None,
        "last_received_at": None,
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
        "language": "ja",
    }

    put = await client.put("/settings", json=body, headers=HEADERS)
    get = await client.get("/settings", headers=HEADERS)

    assert put.status_code == 200
    assert get.json() == {**body, "ingest_token_last_four": None, "last_received_at": None}


# 心拍の 4 つがそろった、保存できる本文。422 のテストはここから 1 か所だけ崩す
VALID = {
    "max_heart_rate": 177,
    "resting_heart_rate": 75,
    "zone_boundary_1": 130,
    "zone_boundary_2": 155,
}


@pytest.mark.parametrize(
    "body",
    [
        {"zone_boundary_1": 160, "zone_boundary_2": 150},
        # 範囲の中で、安静時が最大と同じ（前後関係の検査で落ちる）
        {"max_heart_rate": 110, "resting_heart_rate": 110},
        {"timezone": "Mars/Olympus"},
        # 言語は英語と日本語だけ。省略はできるが null は受け付けない
        {"language": "fr"},
        {"language": None},
        # 心拍の 4 つは必須。空も省略も保存させない
        {"max_heart_rate": None},
        {"resting_heart_rate": None},
        {"zone_boundary_1": None},
        {"zone_boundary_2": None},
    ],
)
async def test_invalid_settings_are_422(client: AsyncClient, body: dict[str, object]) -> None:
    res = await client.put("/settings", json={**VALID, **body}, headers=HEADERS)

    assert res.status_code == 422


@pytest.mark.parametrize(
    "field", ["max_heart_rate", "resting_heart_rate", "zone_boundary_1", "zone_boundary_2"]
)
async def test_heart_rate_settings_cannot_be_left_out(client: AsyncClient, field: str) -> None:
    body = {k: v for k, v in VALID.items() if k != field}

    res = await client.put("/settings", json=body, headers=HEADERS)

    assert res.status_code == 422


async def test_language_can_be_changed_before_heart_rate_is_set(client: AsyncClient) -> None:
    """心拍が空のままでも、言語だけは変えられる。ほかの設定はそのまま。"""
    res = await client.put("/settings/language", json={"language": "ja"}, headers=HEADERS)
    get = await client.get("/settings", headers=HEADERS)

    assert res.status_code == 200
    assert res.json()["language"] == "ja"
    assert get.json() == {
        "max_heart_rate": None,
        "resting_heart_rate": None,
        "zone_boundary_1": None,
        "zone_boundary_2": None,
        "timezone": "Asia/Tokyo",
        "review_weekday": 0,
        "send_notes_to_ai": True,
        "language": "ja",
        "ingest_token_last_four": None,
        "last_received_at": None,
    }


async def test_language_change_keeps_the_other_settings(client: AsyncClient) -> None:
    body = {**VALID, "timezone": "Europe/London", "review_weekday": 6, "send_notes_to_ai": False}
    assert (await client.put("/settings", json=body, headers=HEADERS)).status_code == 200

    res = await client.put("/settings/language", json={"language": "ja"}, headers=HEADERS)

    assert res.json() == {
        **body,
        "language": "ja",
        "ingest_token_last_four": None,
        "last_received_at": None,
    }


async def test_saving_settings_without_language_keeps_the_saved_language(
    client: AsyncClient,
) -> None:
    """言語を言語の窓口で変えたあと、言語を含めずに設定を保存しても英語に戻らない。"""
    await client.put("/settings/language", json={"language": "ja"}, headers=HEADERS)

    res = await client.put("/settings", json=VALID, headers=HEADERS)
    get = await client.get("/settings", headers=HEADERS)

    assert res.status_code == 200
    assert (res.json()["language"], get.json()["language"]) == ("ja", "ja")


async def test_saving_settings_with_language_still_changes_it(client: AsyncClient) -> None:
    await client.put("/settings/language", json={"language": "ja"}, headers=HEADERS)

    res = await client.put("/settings", json={**VALID, "language": "en"}, headers=HEADERS)

    assert res.json()["language"] == "en"


@pytest.mark.parametrize("body", [{"language": "fr"}, {"language": None}, {}])
async def test_invalid_language_is_422(client: AsyncClient, body: dict[str, object]) -> None:
    res = await client.put("/settings/language", json=body, headers=HEADERS)

    assert res.status_code == 422


async def test_language_change_requires_login(client: AsyncClient) -> None:
    res = await client.put("/settings/language", json={"language": "ja"})

    assert res.status_code == 401


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

    first = await client.post("/settings/ingest-token", headers=HEADERS)
    second = await client.post("/settings/ingest-token", headers=HEADERS)

    # 再発行が効いたうえで、他人のトークンが残っている
    assert (first.status_code, second.status_code) == (200, 200)
    settings = await client.get("/settings", headers=HEADERS)
    assert settings.json()["ingest_token_last_four"] == second.json()["last_four"]
    assert await find_user_id_by_token(session, first.json()["token"]) is None
    assert await find_user_id_by_token(session, other_token) == other.id


async def test_last_received_at_is_set_by_the_first_ingest(
    client: AsyncClient, session: AsyncSession
) -> None:
    """導入の案内は、これで最初の送信が届いたかを見る。記録が 0 件の送信でも、届けば入る。"""
    issued = await client.post("/settings/ingest-token", headers=HEADERS)
    before = await client.get("/settings", headers=HEADERS)

    ingest = await client.post(
        "/ingest",
        json={"data": {"workouts": []}},
        headers={"Authorization": f"Bearer {issued.json()['token']}"},
    )
    after = await client.get("/settings", headers=HEADERS)

    assert before.json()["last_received_at"] is None
    assert ingest.status_code == 200
    ingested_at = await session.scalar(
        select(User.last_ingested_at).where(User.firebase_uid == "uid-1")
    )
    assert ingested_at is not None
    assert datetime.fromisoformat(after.json()["last_received_at"]) == ingested_at


async def test_last_received_at_ignores_failed_sends_and_other_users(
    client: AsyncClient, session: AsyncSession
) -> None:
    """断られた送信（中身の形が違う）と、他人への送信では入らない。"""
    issued = await client.post("/settings/ingest-token", headers=HEADERS)
    other = await UserFactory.create_async()
    other_token, _ = await issue_token(session, other.id)

    rejected = await client.post(
        "/ingest",
        json={"workouts": []},
        headers={"Authorization": f"Bearer {issued.json()['token']}"},
    )
    others = await client.post(
        "/ingest",
        json={"data": {"workouts": []}},
        headers={"Authorization": f"Bearer {other_token}"},
    )
    settings = await client.get("/settings", headers=HEADERS)

    assert (rejected.status_code, others.status_code) == (422, 200)
    assert settings.json()["last_received_at"] is None
