from collections.abc import AsyncIterator
from typing import Annotated

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.auth import (
    Identity,
    InvalidTokenError,
    get_identity,
    get_token_verifier,
)


class FakeVerifier:
    """決めたトークンだけ通す偽物。Firebase には触らない。"""

    def verify(self, token: str) -> Identity:
        if token == "good":
            return Identity(uid="uid-1", email="one@example.com")
        raise InvalidTokenError


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """get_identity を使う最小のアプリ。検証だけ偽物に差し替える。"""
    app = FastAPI()

    @app.get("/me")
    def me(identity: Annotated[Identity, Depends(get_identity)]) -> dict[str, str]:
        return {"uid": identity.uid, "email": identity.email}

    app.dependency_overrides[get_token_verifier] = FakeVerifier
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_valid_token_returns_identity(client: AsyncClient) -> None:
    res = await client.get("/me", headers={"Authorization": "Bearer good"})

    assert res.status_code == 200
    assert res.json() == {"uid": "uid-1", "email": "one@example.com"}


async def test_missing_header_is_401(client: AsyncClient) -> None:
    res = await client.get("/me")

    assert res.status_code == 401
    assert res.headers["WWW-Authenticate"] == "Bearer"


async def test_invalid_token_is_401(client: AsyncClient) -> None:
    res = await client.get("/me", headers={"Authorization": "Bearer bad"})

    assert res.status_code == 401
