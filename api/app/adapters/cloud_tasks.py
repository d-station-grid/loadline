"""振り返りを 1 人ずつ作るタスクを Cloud Tasks に積む。

キューの再試行（最大 3 回、60 秒から倍々で最大 10 分）と同時に動かす数（2 本）は、
キューの設定で決める。ここで決めるのは、宛先、付けるトークン、1 回の待ち時間の上限だけ。
"""

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from google.api_core.exceptions import AlreadyExists
from google.cloud import tasks_v2

from app.core.config import Settings
from app.services.auto_reviews import DueReview

logger = logging.getLogger(__name__)

# Gemini を待つ上限（60 秒）と Jev を待つ上限（メモとセリフで 15 秒ずつ）に、材料を読む時間と
# コールドスタートの分を足す
DISPATCH_DEADLINE_SEC = 150
# 積む呼び出し 1 回の上限。Scheduler の 1 回のうちに全員を積み終える
CREATE_TIMEOUT_SEC = 10.0


class TasksClient(Protocol):
    async def create_task(self, *, parent: str, task: tasks_v2.Task, timeout: float) -> Any: ...


def task_id(due: DueReview, at: datetime) -> str:
    """人と週と、積んだ時刻（UTC の時まで）で決める名前。

    同じ時のうちに Scheduler が呼び直しても、同じ名前なので二重に積まない。次の時は別の
    名前になるので、再試行を使い切って消えたタスクも積み直せる（消えたタスクの名前は
    Cloud Tasks が最大 24 時間使わせない）。二重に作らないのは DB の一意制約が受け持つ。
    """
    hour = at.astimezone(UTC).strftime("%Y%m%d%H")
    return f"review-{due.user_id}-{due.period_start.isoformat()}-{hour}"


class CloudTasksReviewQueue:
    def __init__(
        self,
        queue: str,
        base_url: str,
        caller_email: str,
        client_factory: Callable[[], TasksClient] = tasks_v2.CloudTasksAsyncClient,
    ) -> None:
        """queue は projects/.../locations/.../queues/... の形。base_url は api の URL で、
        OIDC トークンの宛先（audience）にも使う。窓口の検証と同じ値を渡す（設定の
        INTERNAL_AUDIENCE。末尾の / は設定を読むときに落としてある）。"""
        self._queue = queue
        self._base_url = base_url
        self._caller_email = caller_email
        self._client_factory = client_factory
        self._client: TasksClient | None = None

    def _tasks(self) -> TasksClient:
        # gRPC の非同期クライアントは動いているイベントループに結び付くので、最初に積むときに
        # 作り、以後は使い回す（片付けられると通信が閉じる）
        if self._client is None:
            self._client = self._client_factory()
        return self._client

    async def enqueue(self, due: DueReview, at: datetime) -> None:
        """1 人分のタスクを積む。at は dispatch の時刻で、タスクの名前に使う。

        同じ名前がもうある（同じ時のうちに積んだ）なら、積めたものとして扱う。

        積めなかったときは google.api_core の例外を上げる。呼ぶ側が残りの人を続ける。
        """
        path = f"/internal/reviews/users/{due.user_id}/weeks/{due.period_start.isoformat()}"
        task = tasks_v2.Task(
            name=f"{self._queue}/tasks/{task_id(due, at)}",
            http_request=tasks_v2.HttpRequest(
                http_method=tasks_v2.HttpMethod.POST,
                url=self._base_url + path,
                oidc_token=tasks_v2.OidcToken(
                    service_account_email=self._caller_email, audience=self._base_url
                ),
            ),
            dispatch_deadline=timedelta(seconds=DISPATCH_DEADLINE_SEC),
        )
        try:
            await self._tasks().create_task(
                parent=self._queue, task=task, timeout=CREATE_TIMEOUT_SEC
            )
        except AlreadyExists:
            # 同じ時のうちに、Scheduler の呼び直しが同じ人を積んだ
            logger.info("tasks: %s is already queued", task_id(due, at))


def review_queue(settings: Settings) -> CloudTasksReviewQueue | None:
    """設定から作る。TASKS_QUEUE が空なら None（見つけた相手をログに出すだけ）。

    認証は Application Default Credentials。本番は Cloud Run のサービスアカウントで、
    キューへの追加と、caller のサービスアカウントの名前でトークンを付ける権限が要る。
    """
    if not settings.tasks_queue:
        return None
    if not settings.internal_audience or not settings.internal_caller_email:
        raise ValueError("TASKS_QUEUE needs INTERNAL_AUDIENCE and INTERNAL_CALLER_EMAIL")
    return CloudTasksReviewQueue(
        settings.tasks_queue, settings.internal_audience, settings.internal_caller_email
    )
