from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from google.api_core.exceptions import AlreadyExists, ServiceUnavailable
from google.cloud import tasks_v2

from app.adapters.cloud_tasks import (
    DISPATCH_DEADLINE_SEC,
    CloudTasksReviewQueue,
    review_queue,
    task_id,
)
from app.core.config import Settings
from app.core.internal_auth import GoogleCerts, GoogleOidcVerifier
from app.services.auto_reviews import DueReview
from tests.test_internal_auth import Fetches, _token

QUEUE = "projects/loadline-app/locations/asia-northeast1/queues/weekly-reviews"
BASE_URL = "https://api.example.run.app"
CALLER = "loadline-invoker@loadline-app.iam.gserviceaccount.com"
DUE = DueReview(user_id=7, period_start=date(2026, 10, 26))
# dispatch の時刻。東京の月曜 6 時は UTC の日曜 21 時
AT = datetime(2026, 11, 1, 21, 0, tzinfo=UTC)


class FakeTasks:
    """create_task に渡されたものを控える。error があれば上げる。"""

    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.error = error

    async def create_task(self, *, parent: str, task: tasks_v2.Task, timeout: float) -> Any:
        self.calls.append({"parent": parent, "task": task, "timeout": timeout})
        if self.error is not None:
            raise self.error
        return task


def _queue(fake: FakeTasks, base_url: str = BASE_URL) -> CloudTasksReviewQueue:
    return CloudTasksReviewQueue(QUEUE, base_url, CALLER, client_factory=lambda: fake)


async def test_enqueues_a_task_for_the_week() -> None:
    fake = FakeTasks()

    await _queue(fake).enqueue(DUE, AT)

    [call] = fake.calls
    task: tasks_v2.Task = call["task"]
    assert call["parent"] == QUEUE
    assert task.name == f"{QUEUE}/tasks/review-7-2026-10-26-2026110121"
    assert task.http_request.http_method == tasks_v2.HttpMethod.POST
    assert task.http_request.url == f"{BASE_URL}/internal/reviews/users/7/weeks/2026-10-26"
    assert task.http_request.oidc_token.service_account_email == CALLER
    assert task.http_request.oidc_token.audience == BASE_URL
    assert task.dispatch_deadline.total_seconds() == DISPATCH_DEADLINE_SEC == 180


def test_task_name_is_per_hour_in_utc() -> None:
    # 同じ時のうちの呼び直しは同じ名前（二重に積まない）
    assert task_id(DUE, AT) == task_id(DUE, datetime(2026, 11, 1, 21, 59, tzinfo=UTC))
    # 次の時は別の名前。再試行を使い切って消えたタスクも積み直せる
    assert task_id(DUE, AT) != task_id(DUE, datetime(2026, 11, 1, 22, 0, tzinfo=UTC))
    # 時刻は UTC にそろえる
    tokyo = AT.astimezone(ZoneInfo("Asia/Tokyo"))
    assert task_id(DUE, tokyo) == "review-7-2026-10-26-2026110121"


async def test_trailing_slash_in_the_setting_still_passes_the_check() -> None:
    # 設定に末尾の / があっても、Tasks が付ける宛先と窓口が検証する宛先が一致する
    settings = Settings(
        tasks_queue=QUEUE, internal_audience=BASE_URL + "/", internal_caller_email=CALLER
    )
    queue = review_queue(settings)
    assert queue is not None
    fake = FakeTasks()
    queue._client_factory = lambda: fake

    await queue.enqueue(DUE, AT)

    task: tasks_v2.Task = fake.calls[0]["task"]
    assert task.http_request.url == f"{BASE_URL}/internal/reviews/users/7/weeks/2026-10-26"
    # Google がこの宛先で署名したトークンを、窓口の検証が通す
    token = _token(aud=task.http_request.oidc_token.audience)
    verifier = GoogleOidcVerifier(
        settings.internal_audience, settings.internal_caller_email, GoogleCerts(fetch=Fetches())
    )
    verifier.verify(token)


async def test_already_queued_counts_as_queued() -> None:
    exists = AlreadyExists("task exists")  # type: ignore[no-untyped-call]

    await _queue(FakeTasks(error=exists)).enqueue(DUE, AT)


async def test_other_errors_are_raised() -> None:
    down = ServiceUnavailable("down")  # type: ignore[no-untyped-call]

    with pytest.raises(ServiceUnavailable):
        await _queue(FakeTasks(error=down)).enqueue(DUE, AT)


async def test_client_is_made_once_on_first_enqueue() -> None:
    made: list[FakeTasks] = []

    def factory() -> FakeTasks:
        made.append(FakeTasks())
        return made[-1]

    queue = CloudTasksReviewQueue(QUEUE, BASE_URL, CALLER, client_factory=factory)
    assert made == []

    await queue.enqueue(DUE, AT)
    await queue.enqueue(DueReview(user_id=8, period_start=date(2026, 10, 26)), AT)

    assert len(made) == 1
    assert len(made[0].calls) == 2


def test_no_queue_without_the_setting() -> None:
    assert review_queue(Settings(tasks_queue="")) is None


def test_queue_needs_the_internal_settings() -> None:
    with pytest.raises(ValueError):
        review_queue(
            Settings(tasks_queue=QUEUE, internal_audience="", internal_caller_email=CALLER)
        )
    with pytest.raises(ValueError):
        review_queue(
            Settings(tasks_queue=QUEUE, internal_audience=BASE_URL, internal_caller_email="")
        )
    assert review_queue(
        Settings(tasks_queue=QUEUE, internal_audience=BASE_URL, internal_caller_email=CALLER)
    )
