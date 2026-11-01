from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import InvalidTokenError
from app.core.internal_auth import get_internal_caller_verifier
from app.domain.calendar import today_for
from app.domain.review_week import review_period
from app.main import app
from app.models import User, WeeklyReview
from app.routers import internal
from app.routers.deps import get_review_queue
from app.services.auto_reviews import (
    AutoReview,
    AutoReviewResult,
    Dispatched,
    DueReview,
    create_for_user,
    dispatch_due_reviews,
    due_reviews,
)
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


@pytest.mark.parametrize(
    "path", ["/internal/reviews/dispatch", "/internal/reviews/users/1/weeks/2026-10-26"]
)
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


def _week_of(day: date) -> date:
    """振り返りの曜日が月曜の人の、day の時点での今の週の初日。"""
    return review_period(day, 0)[0]


async def test_due_on_the_review_day_from_six(session: AsyncSession) -> None:
    due = await _runner()
    await _runner(review_weekday=1)  # 火曜の人
    before_six = await due_reviews(session, datetime(2026, 11, 2, 5, 59, tzinfo=TOKYO))

    assert before_six == []
    # 探したときの週の初日も返す。タスクはこの週だけを作る
    assert await due_reviews(session, MONDAY_6AM_TOKYO) == [DueReview(due.id, date(2026, 10, 26))]


async def test_due_follows_each_users_timezone(session: AsyncSession) -> None:
    tokyo = await _runner()
    utc = await _runner(timezone="UTC")

    # UTC の月曜 6 時は東京の月曜 15 時。どちらも月曜の 6 時を過ぎている
    due = await due_reviews(session, datetime(2026, 11, 2, 6, 0, tzinfo=UTC))
    assert [d.user_id for d in due] == [tokyo.id, utc.id]
    # 東京の月曜 6 時は UTC の日曜 21 時
    assert [d.user_id for d in await due_reviews(session, MONDAY_6AM_TOKYO)] == [tokyo.id]


async def test_not_due_without_heart_rate_settings_or_as_a_guest(session: AsyncSession) -> None:
    await _runner(max_heart_rate=None)
    await _runner(resting_heart_rate=None)
    await _runner(is_demo=True)

    assert await due_reviews(session, MONDAY_6AM_TOKYO) == []


async def test_not_due_when_this_weeks_review_exists(session: AsyncSession) -> None:
    made = await _runner()
    last_week_only = await _runner()
    await WeeklyReviewFactory.create_async(user_id=made.id, period_start=date(2026, 10, 26))
    await WeeklyReviewFactory.create_async(
        user_id=last_week_only.id, period_start=date(2026, 10, 19)
    )

    assert [d.user_id for d in await due_reviews(session, MONDAY_6AM_TOKYO)] == [last_week_only.id]


async def test_dispatch_returns_the_due_users(client: AsyncClient) -> None:
    # 今の時刻で呼ぶので、誰が当たるかは決められない。当たらない人だけ置いて空を確かめる
    await _runner(max_heart_rate=None)

    res = await client.post("/internal/reviews/dispatch", headers=HEADERS)

    assert res.status_code == 200
    assert res.json() == {"reviews": []}


class FakeQueue:
    """積んだ相手を控える。fail_for の人だけ失敗させる。"""

    def __init__(self, fail_for: set[int] | None = None) -> None:
        self.enqueued: list[DueReview] = []
        self.at: list[datetime] = []
        self.fail_for = fail_for or set()

    async def enqueue(self, due: DueReview, at: datetime) -> None:
        if due.user_id in self.fail_for:
            raise RuntimeError("tasks is down")
        self.enqueued.append(due)
        self.at.append(at)


async def test_dispatch_enqueues_each_due_user(session: AsyncSession) -> None:
    first = await _runner()
    second = await _runner()
    await _runner(review_weekday=1)
    queue = FakeQueue()

    done = await dispatch_due_reviews(session, queue, MONDAY_6AM_TOKYO)

    expected = [DueReview(u.id, date(2026, 10, 26)) for u in (first, second)]
    assert queue.enqueued == expected
    # タスクの名前に使う時刻は dispatch の時刻
    assert queue.at == [MONDAY_6AM_TOKYO, MONDAY_6AM_TOKYO]
    assert done == Dispatched(due=expected, failed=[])


async def test_dispatch_keeps_going_when_one_fails(session: AsyncSession) -> None:
    first = await _runner()
    second = await _runner()
    queue = FakeQueue(fail_for={first.id})

    done = await dispatch_due_reviews(session, queue, MONDAY_6AM_TOKYO)

    # 1 人目が積めなくても 2 人目は積む
    assert queue.enqueued == [DueReview(second.id, date(2026, 10, 26))]
    assert done.failed == [DueReview(first.id, date(2026, 10, 26))]


async def test_dispatch_without_a_queue_only_finds(session: AsyncSession) -> None:
    user = await _runner()

    done = await dispatch_due_reviews(session, None, MONDAY_6AM_TOKYO)

    assert done == Dispatched(due=[DueReview(user.id, date(2026, 10, 26))], failed=[])


async def test_dispatch_is_500_when_some_could_not_be_queued(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    due = [DueReview(1, date(2026, 10, 26)), DueReview(2, date(2026, 10, 26))]

    async def fake_dispatch(*_args: Any) -> Dispatched:
        return Dispatched(due=due, failed=due[:1])

    monkeypatch.setattr(internal, "dispatch_due_reviews", fake_dispatch)

    res = await client.post("/internal/reviews/dispatch", headers=HEADERS)

    assert res.status_code == 500
    assert res.json() == {"detail": "could not enqueue 1 of 2 reviews"}


async def test_dispatch_endpoint_uses_the_configured_queue(client: AsyncClient) -> None:
    # 窓口が queue の依存を service に渡していること。今の時刻では誰が当たるか決められないので、
    # 当たる人がいないことと、積まないことだけ見る
    queue = FakeQueue()
    app.dependency_overrides[get_review_queue] = lambda: queue
    await _runner(max_heart_rate=None)

    res = await client.post("/internal/reviews/dispatch", headers=HEADERS)

    assert res.status_code == 200
    assert queue.enqueued == []


# 1 人分を作る


async def _review_count(session: AsyncSession, user: User) -> int:
    stmt = select(func.count()).select_from(WeeklyReview).where(WeeklyReview.user_id == user.id)
    return (await session.scalar(stmt)) or 0


def _task_path(user: User | int, start: date | str) -> str:
    user_id = user if isinstance(user, int) else user.id
    return f"/internal/reviews/users/{user_id}/weeks/{start}"


def _current_week() -> date:
    return _week_of(today_for("Asia/Tokyo"))


async def test_task_creates_the_review_once(client: AsyncClient, session: AsyncSession) -> None:
    user = await _runner()

    first = await client.post(_task_path(user, _current_week()), headers=HEADERS)
    again = await client.post(_task_path(user, _current_week()), headers=HEADERS)

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

    res = await client.post(_task_path(user, _current_week()), headers=HEADERS)

    assert res.status_code == 200
    assert res.json() == {"result": "skipped", "review_id": None}
    assert await _review_count(session, user) == 0


async def test_task_for_a_past_week_is_skipped(client: AsyncClient, session: AsyncSession) -> None:
    user = await _runner()

    res = await client.post(_task_path(user, _current_week() - timedelta(weeks=1)), headers=HEADERS)

    assert res.json() == {"result": "skipped", "review_id": None}
    assert await _review_count(session, user) == 0


async def test_task_after_the_review_weekday_changed_is_skipped(
    client: AsyncClient, session: AsyncSession
) -> None:
    # 月曜の週で積んだ後、本人が振り返りの曜日を木曜に変えた
    user = await _runner(review_weekday=3)

    res = await client.post(_task_path(user, _current_week()), headers=HEADERS)

    assert res.json() == {"result": "skipped", "review_id": None}
    assert await _review_count(session, user) == 0


async def test_task_for_a_missing_user_is_404(client: AsyncClient) -> None:
    res = await client.post(_task_path(999999, _current_week()), headers=HEADERS)

    assert res.status_code == 404


async def test_task_with_a_broken_date_is_422(client: AsyncClient) -> None:
    user = await _runner()

    res = await client.post(_task_path(user, "2026-13-01"), headers=HEADERS)

    assert res.status_code == 422


# 遅れて届いたタスク。時刻を決めて service を呼ぶ


@pytest.mark.parametrize(
    "now",
    [
        datetime(2026, 11, 3, 1, 0, tzinfo=TOKYO),  # 翌日（火曜）
        datetime(2026, 11, 8, 23, 59, tzinfo=TOKYO),  # 次の振り返りの曜日の前の晩（日曜）
    ],
    ids=["tuesday", "sunday-night"],
)
async def test_late_task_within_the_same_week_creates(session: AsyncSession, now: datetime) -> None:
    user = await _runner()

    done = await create_for_user(session, user.id, date(2026, 10, 26), None, now=now)

    assert done.result == AutoReviewResult.CREATED
    review = await session.get(WeeklyReview, done.review_id)
    assert review is not None
    assert review.period_start == date(2026, 10, 26)


@pytest.mark.parametrize(
    "now",
    [
        datetime(2026, 11, 9, 0, 0, tzinfo=TOKYO),
        datetime(2026, 11, 9, 5, 59, tzinfo=TOKYO),
        datetime(2026, 11, 9, 6, 0, tzinfo=TOKYO),
    ],
    ids=["next-monday-0am", "next-monday-5:59am", "next-monday-6am"],
)
async def test_task_late_into_the_next_review_day_is_skipped(
    session: AsyncSession, now: datetime
) -> None:
    # 11/2（月）に積んだ 10/26 の週のタスク。次の月曜には今の週が 11/2 に変わる。
    # 作れば次の週を記録を待つ 6 時より前に確定してしまうので、作らない
    user = await _runner()

    done = await create_for_user(session, user.id, date(2026, 10, 26), None, now=now)

    assert done == AutoReview(AutoReviewResult.SKIPPED)
    assert await _review_count(session, user) == 0
