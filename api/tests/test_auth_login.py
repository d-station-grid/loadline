from collections.abc import Iterator
from importlib.resources import files

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Identity, InvalidTokenError, get_token_verifier
from app.main import app
from app.models import User

HEADERS = {"Authorization": "Bearer good"}


class FakeVerifier:
    def verify(self, token: str) -> Identity:
        if token == "good":
            return Identity(uid="uid-1", email="one@example.com")
        raise InvalidTokenError


@pytest.fixture(autouse=True)
def fake_verifier() -> Iterator[None]:
    """このファイルのテストでは、トークンの検証を偽物にする。"""
    app.dependency_overrides[get_token_verifier] = FakeVerifier
    yield
    app.dependency_overrides.pop(get_token_verifier, None)


async def _count_users(session: AsyncSession) -> int:
    return await session.scalar(select(func.count()).select_from(User)) or 0


async def test_first_login_creates_user(client: AsyncClient, session: AsyncSession) -> None:
    assert await _count_users(session) == 0

    res = await client.post("/auth/login", headers=HEADERS)

    assert res.status_code == 200
    body = res.json()
    assert body["email"] == "one@example.com"
    assert isinstance(body["id"], int)
    user = await session.scalar(select(User).where(User.firebase_uid == "uid-1"))
    assert user is not None
    assert user.id == body["id"]


async def test_second_login_returns_same_user(client: AsyncClient, session: AsyncSession) -> None:
    first = await client.post("/auth/login", headers=HEADERS)
    second = await client.post("/auth/login", headers=HEADERS)

    assert first.json()["id"] == second.json()["id"]
    assert await _count_users(session) == 1


async def test_login_without_token_is_401(client: AsyncClient) -> None:
    res = await client.post("/auth/login")

    assert res.status_code == 401


async def _login_and_get_timezone(
    client: AsyncClient, session: AsyncSession, body: dict[str, object] | None
) -> str:
    res = await client.post("/auth/login", headers=HEADERS, json=body)
    assert res.status_code == 200
    user = await session.scalar(select(User).where(User.firebase_uid == "uid-1"))
    assert user is not None
    await session.refresh(user)
    return user.timezone


async def test_first_login_uses_browser_timezone(
    client: AsyncClient, session: AsyncSession
) -> None:
    timezone = await _login_and_get_timezone(client, session, {"timezone": "America/New_York"})

    assert timezone == "America/New_York"


# ブラウザ（ICU）が返す旧名。Debian 13 の slim イメージの OS のデータにはない
LEGACY_NAMES = ["Asia/Calcutta", "America/Indianapolis", "Europe/Kiev"]


@pytest.mark.parametrize("name", LEGACY_NAMES)
async def test_first_login_keeps_legacy_timezone_name(
    client: AsyncClient, session: AsyncSession, name: str
) -> None:
    timezone = await _login_and_get_timezone(client, session, {"timezone": name})

    assert timezone == name


@pytest.mark.parametrize("name", LEGACY_NAMES)
def test_tzdata_package_has_legacy_name(name: str) -> None:
    # OS のデータに旧名がなくても、ZoneInfo は tzdata パッケージから読む。手元の OS のデータで
    # 上のテストが通ってしまうので、パッケージそのものに入っていることを確かめる
    assert files("tzdata.zoneinfo").joinpath(name).is_file()


@pytest.mark.parametrize(
    "body",
    [None, {}, {"timezone": None}, {"timezone": ""}, {"timezone": "Mars/Olympus_Mons"}],
)
async def test_first_login_falls_back_to_default_timezone(
    client: AsyncClient, session: AsyncSession, body: dict[str, object] | None
) -> None:
    timezone = await _login_and_get_timezone(client, session, body)

    assert timezone == "Asia/Tokyo"


async def test_later_login_keeps_existing_timezone(
    client: AsyncClient, session: AsyncSession
) -> None:
    await client.post("/auth/login", headers=HEADERS, json={"timezone": "Europe/London"})

    timezone = await _login_and_get_timezone(client, session, {"timezone": "America/New_York"})

    assert timezone == "Europe/London"


async def _login_and_get_language(
    client: AsyncClient, session: AsyncSession, body: dict[str, object] | None
) -> str:
    res = await client.post("/auth/login", headers=HEADERS, json=body)
    assert res.status_code == 200
    user = await session.scalar(select(User).where(User.firebase_uid == "uid-1"))
    assert user is not None
    await session.refresh(user)
    return user.language


@pytest.mark.parametrize("tag", ["ja", "ja-JP", "JA-jp", "ja_JP"])
async def test_first_login_uses_browser_language(
    client: AsyncClient, session: AsyncSession, tag: str
) -> None:
    """地域の部分と大文字・小文字は見ない。"""
    assert await _login_and_get_language(client, session, {"language": tag}) == "ja"


@pytest.mark.parametrize(
    "body",
    [None, {}, {"language": None}, {"language": ""}, {"language": "fr-FR"}, {"language": "en-GB"}],
)
async def test_first_login_falls_back_to_english(
    client: AsyncClient, session: AsyncSession, body: dict[str, object] | None
) -> None:
    """知らない言語は 422 にせず、英語で作る。"""
    assert await _login_and_get_language(client, session, body) == "en"


async def test_later_login_keeps_existing_language(
    client: AsyncClient, session: AsyncSession
) -> None:
    """2 回目からは本文を見ない。設定の画面で変える。"""
    await client.post("/auth/login", headers=HEADERS, json={"language": "en-US"})

    assert await _login_and_get_language(client, session, {"language": "ja-JP"}) == "en"


async def test_login_returns_the_language(client: AsyncClient) -> None:
    """web はログインの直後から、応答の言語で画面を出す。"""
    res = await client.post("/auth/login", headers=HEADERS, json={"language": "ja-JP"})

    assert res.status_code == 200
    assert res.json()["language"] == "ja"
