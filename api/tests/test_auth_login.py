from collections.abc import Iterator

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
