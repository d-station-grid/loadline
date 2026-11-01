from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import InvalidTokenError
from app.core.internal_auth import get_internal_caller_verifier
from app.domain.review_week import review_period
from app.main import app
from app.models import User, WeeklyReview
from app.services.auto_reviews import due_user_ids
from tests.factories import UserFactory, WeeklyReviewFactory

HEADERS = {"Authorization": "Bearer from-google"}
TOKYO = ZoneInfo("Asia/Tokyo")
# 2026-11-02 は月曜。東京の 6 時は UTC の前日 21 時
MONDAY_6AM_TOKYO = datetime(2026, 11, 2, 6, 0, tzinfo=TOKYO)


class FakeCallerVerifier:
    def verify(self, token: str) -> None:
        if token != "from-google":
            raise InvalidTokenError


@pytest.fixture(autouse=True)
def fake_caller() -> Iterator[None]:
    app.dependency_overrides[get_internal_caller_verifier] = FakeCallerVerifier
    yield
    app.dependency_overrides.pop(get_internal_caller_verifier, None)


async def _runner(**fields: Any) -> User:
    """心拍の設定がある、振り返りの曜日が月曜の人。"""
    defaults: dict[str, Any] = {
        "max_heart_rate": 177,
        "resting_heart_rate": 75,
        "timezone": "Asia/Tokyo",
        "review_weekday": 0,
    }
    return await UserFactory.create_async(**{**defaults, **fields})


# 呼び出し元の確認


@pytest.mark.parametrize("path", ["/internal/reviews/dispatch", "/internal/reviews/users/1"])
@pytest.mark.parametrize(
    "headers", [{}, {"Authorization": "Bearer forged"}], ids=["no-token", "bad-token"]
)
async def test_internal_endpoints_need_googles_token(
    client: AsyncClient, path: str, headers: dict[str, str]
) -> None:
    res = await client.post(path, headers=headers)

    assert res.status_code == 401


async def test_not_configured_rejects_everyone(client: AsyncClient) -> None:
    # 偽物を外すと、設定の空な本物で検証する。手元や CI で窓口が開いたままにならない
    app.dependency_overrides.pop(get_internal_caller_verifier)
    get_internal_caller_verifier.cache_clear()

    res = await client.post("/internal/reviews/dispatch", headers=HEADERS)

    assert res.status_code == 401


async def test_internal_endpoints_are_not_in_the_openapi(client: AsyncClient) -> None:
    paths = (await client.get("/openapi.json")).json()["paths"]

    assert not [p for p in paths if p.startswith("/internal")]


# 相手を探す


async def test_due_on_the_review_day_from_six(session: AsyncSession) -> None:
    due = await _runner()
    await _runner(review_weekday=1)  # 火曜の人
    before_six = await due_user_ids(session, datetime(2026, 11, 2, 5, 59, tzinfo=TOKYO))

    assert before_six == []
    assert await due_user_ids(session, MONDAY_6AM_TOKYO) == [due.id]


async def test_due_follows_each_users_timezone(session: AsyncSession) -> None:
    tokyo = await _runner()
    utc = await _runner(timezone="UTC")

    # UTC の月曜 6 時は東京の月曜 15 時。どちらも月曜の 6 時を過ぎている
    assert await due_user_ids(session, datetime(2026, 11, 2, 6, 0, tzinfo=UTC)) == [
        tokyo.id,
        utc.id,
    ]
    # 東京の月曜 6 時は UTC の日曜 21 時
    assert await due_user_ids(session, MONDAY_6AM_TOKYO) == [tokyo.id]


async def test_not_due_without_heart_rate_settings_or_as_a_guest(session: AsyncSession) -> None:
    await _runner(max_heart_rate=None)
    await _runner(resting_heart_rate=None)
    await _runner(is_demo=True)

    assert await due_user_ids(session, MONDAY_6AM_TOKYO) == []


async def test_not_due_when_this_weeks_review_exists(session: AsyncSession) -> None:
    made = await _runner()
    last_week_only = await _runner()
    start, _ = review_period(date(2026, 11, 2), 0)
    await WeeklyReviewFactory.create_async(user_id=made.id, period_start=start)
    await WeeklyReviewFactory.create_async(
        user_id=last_week_only.id, period_start=date(2026, 10, 19)
    )

    assert await due_user_ids(session, MONDAY_6AM_TOKYO) == [last_week_only.id]


async def test_dispatch_returns_the_due_users(client: AsyncClient) -> None:
    # 今の時刻で呼ぶので、誰が当たるかは決められない。当たらない人だけ置いて空を確かめる
    await _runner(max_heart_rate=None)

    res = await client.post("/internal/reviews/dispatch", headers=HEADERS)

    assert res.status_code == 200
    assert res.json() == {"user_ids": []}


# 1 人分を作る


async def _review_count(session: AsyncSession, user: User) -> int:
    stmt = select(func.count()).select_from(WeeklyReview).where(WeeklyReview.user_id == user.id)
    return (await session.scalar(stmt)) or 0


async def test_task_creates_the_review_once(client: AsyncClient, session: AsyncSession) -> None:
    user = await _runner()

    first = await client.post(f"/internal/reviews/users/{user.id}", headers=HEADERS)
    again = await client.post(f"/internal/reviews/users/{user.id}", headers=HEADERS)

    assert first.status_code == 200
    assert first.json()["result"] == "created"
    # Tasks が同じ人を 2 回呼んでも、2 通目は作らない
    assert again.json() == {"result": "exists", "review_id": first.json()["review_id"]}
    assert await _review_count(session, user) == 1


@pytest.mark.parametrize(
    "fields", [{"max_heart_rate": None}, {"is_demo": True}], ids=["no-heart-rate", "guest"]
)
async def test_task_skips_who_cannot_have_a_review(
    client: AsyncClient, session: AsyncSession, fields: dict[str, Any]
) -> None:
    # 積んだ後に設定を消した・ゲストになった人。やり直しても変わらないので 2xx で返す
    user = await _runner(**fields)

    res = await client.post(f"/internal/reviews/users/{user.id}", headers=HEADERS)

    assert res.status_code == 200
    assert res.json() == {"result": "skipped", "review_id": None}
    assert await _review_count(session, user) == 0


async def test_task_for_a_missing_user_is_404(client: AsyncClient) -> None:
    res = await client.post("/internal/reviews/users/999999", headers=HEADERS)

    assert res.status_code == 404
