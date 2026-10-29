from collections.abc import Iterator
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient

from app.core.auth import Identity, InvalidTokenError, get_token_verifier
from app.domain.review_week import review_period
from app.main import app
from app.models import User
from tests.factories import (
    UserFactory,
    WeeklyReviewFactory,
    WeeklyReviewOptionFactory,
    WorkoutFactory,
)

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


async def _me(**fields: Any) -> User:
    """ログインする本人（uid-1）。心拍の設定は入れておく。"""
    defaults: dict[str, Any] = {
        "max_heart_rate": 177,
        "resting_heart_rate": 75,
        "timezone": "Asia/Tokyo",
        "review_weekday": 0,
    }
    return await UserFactory.create_async(firebase_uid="uid-1", **{**defaults, **fields})


def _current_period(timezone: str, weekday: int) -> tuple[str, str]:
    start, end = review_period(datetime.now(ZoneInfo(timezone)).date(), weekday)
    return start.isoformat(), end.isoformat()


async def test_post_creates_the_review_of_the_current_week(client: AsyncClient) -> None:
    await _me(review_weekday=3)

    res = await client.post("/reviews", headers=HEADERS)

    assert res.status_code == 201
    body = res.json()
    assert (body["period_start"], body["period_end"]) == _current_period("Asia/Tokyo", 3)
    assert body["situation"] == "not_enough_data"
    assert body["is_fallback"] is True
    assert body["status"] == "completed"
    assert [o["position"] for o in body["options"]] == list(range(len(body["options"])))
    assert 2 <= len(body["options"]) <= 3


async def test_post_again_returns_the_same_review_with_200(client: AsyncClient) -> None:
    await _me()
    first = (await client.post("/reviews", headers=HEADERS)).json()

    res = await client.post("/reviews", headers=HEADERS)

    assert res.status_code == 200
    assert res.json() == first


async def test_post_without_heart_rate_settings_is_409(client: AsyncClient) -> None:
    await _me(resting_heart_rate=None)

    res = await client.post("/reviews", headers=HEADERS)

    assert res.status_code == 409


async def test_guest_cannot_create_a_review(client: AsyncClient) -> None:
    """ゲスト（デモの利用者）は見るだけ。"""
    await _me(is_demo=True)

    res = await client.post("/reviews", headers=HEADERS)

    assert res.status_code == 403


async def test_current_is_404_before_the_first_review(client: AsyncClient) -> None:
    await _me()

    res = await client.get("/reviews/current", headers=HEADERS)

    assert res.status_code == 404


async def test_current_returns_the_created_review(client: AsyncClient) -> None:
    await _me()
    created = (await client.post("/reviews", headers=HEADERS)).json()

    res = await client.get("/reviews/current", headers=HEADERS)

    assert res.status_code == 200
    assert res.json() == created


async def test_current_does_not_show_an_older_week(client: AsyncClient) -> None:
    """前の週の振り返りがあっても、今の週のものがなければ 404。"""
    me = await _me()
    start, _ = _current_period("Asia/Tokyo", 0)
    await WeeklyReviewFactory.create_async(
        user_id=me.id, period_start=date.fromisoformat(start) - timedelta(weeks=1)
    )

    res = await client.get("/reviews/current", headers=HEADERS)

    assert res.status_code == 404


async def test_current_does_not_show_someone_elses_review(client: AsyncClient) -> None:
    await _me()
    other = await UserFactory.create_async(review_weekday=0, timezone="Asia/Tokyo")
    start, _ = _current_period("Asia/Tokyo", 0)
    await WeeklyReviewFactory.create_async(user_id=other.id, period_start=date.fromisoformat(start))

    res = await client.get("/reviews/current", headers=HEADERS)

    assert res.status_code == 404


async def test_post_does_not_count_someone_elses_workouts(client: AsyncClient) -> None:
    """自分は 1 回、他人は同じ週に 2 回。振り返りの回数は自分の 1 回だけ。"""
    me = await _me()
    other = await UserFactory.create_async(max_heart_rate=177, resting_heart_rate=75)
    start, _ = _current_period("Asia/Tokyo", 0)
    day = datetime.combine(
        date.fromisoformat(start) + timedelta(days=1), time(7), tzinfo=ZoneInfo("Asia/Tokyo")
    )
    await WorkoutFactory.create_async(user_id=me.id, started_at=day)
    for hours in (0, 3):
        await WorkoutFactory.create_async(user_id=other.id, started_at=day + timedelta(hours=hours))

    res = await client.post("/reviews", headers=HEADERS)

    assert res.status_code == 201
    assert "This week you did 1 session" in res.json()["script"]


async def test_put_selection_selects_and_reselects(client: AsyncClient) -> None:
    await _me()
    review = (await client.post("/reviews", headers=HEADERS)).json()
    first, second = review["options"][0]["id"], review["options"][1]["id"]

    res = await client.put(
        f"/reviews/{review['id']}/selection", json={"option_id": first}, headers=HEADERS
    )
    assert res.status_code == 200
    assert [o["selected_at"] is not None for o in res.json()["options"]][:2] == [True, False]

    res = await client.put(
        f"/reviews/{review['id']}/selection", json={"option_id": second}, headers=HEADERS
    )
    assert res.status_code == 200
    assert [o["selected_at"] is not None for o in res.json()["options"]][:2] == [False, True]
    current = (await client.get("/reviews/current", headers=HEADERS)).json()
    assert current == res.json()


async def test_put_selection_of_a_past_week_is_409(client: AsyncClient) -> None:
    me = await _me()
    start, _ = _current_period("Asia/Tokyo", 0)
    past = await WeeklyReviewFactory.create_async(
        user_id=me.id, period_start=date.fromisoformat(start) - timedelta(weeks=1)
    )
    option = await WeeklyReviewOptionFactory.create_async(weekly_review_id=past.id)

    res = await client.put(
        f"/reviews/{past.id}/selection", json={"option_id": option.id}, headers=HEADERS
    )

    assert res.status_code == 409


async def test_put_selection_of_someone_elses_review_is_404(client: AsyncClient) -> None:
    await _me()
    other = await UserFactory.create_async(review_weekday=0, timezone="Asia/Tokyo")
    start, _ = _current_period("Asia/Tokyo", 0)
    theirs = await WeeklyReviewFactory.create_async(
        user_id=other.id, period_start=date.fromisoformat(start)
    )
    option = await WeeklyReviewOptionFactory.create_async(weekly_review_id=theirs.id)

    res = await client.put(
        f"/reviews/{theirs.id}/selection", json={"option_id": option.id}, headers=HEADERS
    )

    assert res.status_code == 404


async def test_put_selection_with_an_option_of_another_review_is_404(client: AsyncClient) -> None:
    me = await _me()
    review = (await client.post("/reviews", headers=HEADERS)).json()
    start, _ = _current_period("Asia/Tokyo", 0)
    past = await WeeklyReviewFactory.create_async(
        user_id=me.id, period_start=date.fromisoformat(start) - timedelta(weeks=1)
    )
    option = await WeeklyReviewOptionFactory.create_async(weekly_review_id=past.id)

    res = await client.put(
        f"/reviews/{review['id']}/selection", json={"option_id": option.id}, headers=HEADERS
    )

    assert res.status_code == 404


async def test_guest_cannot_select_an_option(client: AsyncClient) -> None:
    me = await _me(is_demo=True)
    start, _ = _current_period("Asia/Tokyo", 0)
    review = await WeeklyReviewFactory.create_async(
        user_id=me.id, period_start=date.fromisoformat(start)
    )
    option = await WeeklyReviewOptionFactory.create_async(weekly_review_id=review.id)

    res = await client.put(
        f"/reviews/{review.id}/selection", json={"option_id": option.id}, headers=HEADERS
    )

    assert res.status_code == 403


@pytest.mark.parametrize(
    ("method", "path"),
    [("post", "/reviews"), ("get", "/reviews/current"), ("put", "/reviews/1/selection")],
)
async def test_reviews_need_login(client: AsyncClient, method: str, path: str) -> None:
    res = await client.request(method.upper(), path, json={"option_id": 1})

    assert res.status_code == 401
