import asyncio
from collections.abc import AsyncIterator, Iterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import JSONResponse
from starlette.types import Receive, Scope, Send

from app.core.auth import Identity, InvalidTokenError, get_token_verifier
from app.core.body_limit import MAX_BODY_BYTES, MAX_INGEST_BODY_BYTES, BodySizeLimitMiddleware
from app.core.rate_limit import RateLimiter
from app.main import app
from app.routers.deps import get_ingest_limiter, get_write_limiter
from app.services.ingest_tokens import current_token, issue_token
from tests.factories import UserFactory

ONE = {"Authorization": "Bearer one"}
TWO = {"Authorization": "Bearer two"}
SETTINGS = {
    "max_heart_rate": 180,
    "resting_heart_rate": 50,
    "zone_boundary_1": 130,
    "zone_boundary_2": 155,
    "timezone": "Asia/Tokyo",
    "review_weekday": 0,
    "send_notes_to_ai": True,
    "language": "en",
}


class FakeVerifier:
    def verify(self, token: str) -> Identity:
        if token == "one":
            return Identity(uid="uid-1", email="one@example.com")
        if token == "two":
            return Identity(uid="uid-2", email="two@example.com")
        raise InvalidTokenError


@pytest.fixture(autouse=True)
def fake_verifier() -> Iterator[None]:
    app.dependency_overrides[get_token_verifier] = FakeVerifier
    yield
    app.dependency_overrides.pop(get_token_verifier, None)


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def test_limiter_stops_at_the_limit_and_opens_in_the_next_window() -> None:
    clock = Clock()
    limiter = RateLimiter(2, window_sec=60, clock=clock)

    assert limiter.hit("a") is None
    assert limiter.hit("a") is None
    clock.now += 10
    assert limiter.hit("a") == 50
    clock.now += 50
    assert limiter.hit("a") is None


def test_limiter_counts_each_key_separately() -> None:
    limiter = RateLimiter(1, clock=Clock())

    assert limiter.hit("a") is None
    assert limiter.hit("a") is not None
    assert limiter.hit("b") is None


def test_rejected_hits_do_not_extend_the_window() -> None:
    clock = Clock()
    limiter = RateLimiter(1, window_sec=60, clock=clock)

    limiter.hit("a")
    clock.now += 59
    assert limiter.hit("a") == 1
    clock.now += 1
    assert limiter.hit("a") is None


async def test_writes_over_the_limit_are_429_for_that_user_only(client: AsyncClient) -> None:
    limiter = RateLimiter(2)
    app.dependency_overrides[get_write_limiter] = lambda: limiter
    await client.post("/auth/login", headers=ONE)
    await client.post("/auth/login", headers=TWO)

    for _ in range(2):
        assert (await client.put("/settings", json=SETTINGS, headers=ONE)).status_code == 200
    res = await client.put("/settings", json=SETTINGS, headers=ONE)

    assert res.status_code == 429
    assert int(res.headers["Retry-After"]) >= 1
    assert (await client.put("/settings", json=SETTINGS, headers=TWO)).status_code == 200
    # 読み取りは数えない
    assert (await client.get("/settings", headers=ONE)).status_code == 200


async def test_login_over_the_limit_is_429(client: AsyncClient) -> None:
    limiter = RateLimiter(1)
    app.dependency_overrides[get_write_limiter] = lambda: limiter

    assert (await client.post("/auth/login", headers=ONE)).status_code == 200
    assert (await client.post("/auth/login", headers=ONE)).status_code == 429


async def test_ingest_over_the_limit_is_429(client: AsyncClient, session: AsyncSession) -> None:
    limiter = RateLimiter(1)
    app.dependency_overrides[get_ingest_limiter] = lambda: limiter
    user = await UserFactory.create_async()
    token, _ = await issue_token(session, user.id)
    headers = {"Authorization": f"Bearer {token}"}
    body: dict[str, dict[str, list[str]]] = {"data": {"workouts": []}}

    assert (await client.post("/ingest", json=body, headers=headers)).status_code == 200
    res = await client.post("/ingest", json=body, headers=headers)

    assert res.status_code == 429
    assert "Retry-After" in res.headers


async def test_ingest_over_the_limit_does_not_update_last_used_at(
    client: AsyncClient, session: AsyncSession
) -> None:
    limiter = RateLimiter(1)
    app.dependency_overrides[get_ingest_limiter] = lambda: limiter
    user = await UserFactory.create_async()
    token, _ = await issue_token(session, user.id)
    headers = {"Authorization": f"Bearer {token}"}
    body: dict[str, dict[str, list[str]]] = {"data": {"workouts": []}}
    await client.post("/ingest", json=body, headers=headers)
    row = await current_token(session, user.id)
    assert row is not None
    used_at = row.last_used_at
    assert used_at is not None

    assert (await client.post("/ingest", json=body, headers=headers)).status_code == 429

    await session.refresh(row)
    assert row.last_used_at == used_at


async def test_wrong_ingest_token_is_not_counted(client: AsyncClient) -> None:
    limiter = RateLimiter(1)
    app.dependency_overrides[get_ingest_limiter] = lambda: limiter
    headers = {"Authorization": "Bearer wrong"}

    for _ in range(2):
        res = await client.post("/ingest", json={"data": {}}, headers=headers)
        assert res.status_code == 401


async def test_body_over_the_limit_is_413(client: AsyncClient) -> None:
    res = await client.post("/notes", content=b"x" * (MAX_BODY_BYTES + 1), headers=ONE)

    assert res.status_code == 413


async def test_ingest_accepts_a_larger_body_than_other_paths(client: AsyncClient) -> None:
    """取り込みの上限の内なら、本文の大きさでは止めず、認証まで進む。"""
    res = await client.post("/ingest", content=b"x" * (MAX_BODY_BYTES + 1))

    assert res.status_code != 413
    too_large = await client.post("/ingest", content=b"x" * (MAX_INGEST_BODY_BYTES + 1))
    assert too_large.status_code == 413


async def test_body_without_content_length_is_counted(client: AsyncClient) -> None:
    async def chunks() -> AsyncIterator[bytes]:
        for _ in range(3):
            yield b"x" * (MAX_BODY_BYTES // 2)

    res = await client.post("/notes", content=chunks(), headers=ONE)

    assert res.status_code == 413


class HeldApp:
    """本文を読んだあと、release されるまで応答しない。"""

    def __init__(self) -> None:
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await receive()
        self.entered.set()
        await self.release.wait()
        await JSONResponse({"ok": True})(scope, receive, send)


async def test_total_body_over_the_limit_is_503_until_the_first_finishes() -> None:
    held = HeldApp()
    guarded = BodySizeLimitMiddleware(held, max_inflight_bytes=10)
    async with AsyncClient(transport=ASGITransport(app=guarded), base_url="http://t") as c:
        first = asyncio.create_task(c.post("/notes", content=b"x" * 6))
        await held.entered.wait()

        second = await c.post("/notes", content=b"x" * 6)
        assert second.status_code == 503
        assert second.headers["Retry-After"] == "5"

        held.release.set()
        assert (await first).status_code == 200
        assert (await c.post("/notes", content=b"x" * 6)).status_code == 200


async def test_total_counts_bodies_without_content_length() -> None:
    held = HeldApp()
    guarded = BodySizeLimitMiddleware(held, max_inflight_bytes=10)

    async def chunks() -> AsyncIterator[bytes]:
        for _ in range(3):
            yield b"x" * 3

    async with AsyncClient(transport=ASGITransport(app=guarded), base_url="http://t") as c:
        first = asyncio.create_task(c.post("/notes", content=b"x" * 6))
        await held.entered.wait()
        assert (await c.post("/notes", content=chunks())).status_code == 503
        held.release.set()
        assert (await first).status_code == 200


async def test_total_is_released_when_the_app_raises() -> None:
    calls = 0

    async def failing(scope: Scope, receive: Receive, send: Send) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError
        await JSONResponse({"ok": True})(scope, receive, send)

    guarded = BodySizeLimitMiddleware(failing, max_inflight_bytes=10)
    async with AsyncClient(transport=ASGITransport(app=guarded), base_url="http://t") as c:
        with pytest.raises(RuntimeError):
            await c.post("/notes", content=b"x" * 6)
        assert (await c.post("/notes", content=b"x" * 6)).status_code == 200
