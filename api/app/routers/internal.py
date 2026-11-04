"""Cloud Scheduler と Cloud Tasks だけが呼ぶ窓口。

利用者の画面からは使わないので、OpenAPI（web の型）には載せない。
"""

import logging
from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.core.internal_auth import require_internal_caller
from app.routers.deps import DbSession, LineCheckerDep, ReviewQueueDep, ReviewWriterDep
from app.services.auto_reviews import (
    AutoReviewResult,
    create_for_user,
    dispatch_due_reviews,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/internal",
    dependencies=[Depends(require_internal_caller)],
    include_in_schema=False,
)


class DueReviewOut(BaseModel):
    user_id: int
    period_start: date


class DispatchOut(BaseModel):
    reviews: list[DueReviewOut]


class AutoReviewOut(BaseModel):
    result: AutoReviewResult
    review_id: int | None


@router.post("/reviews/dispatch")
async def dispatch_reviews(session: DbSession, queue: ReviewQueueDep) -> DispatchOut:
    """Scheduler が 1 時間おきに呼ぶ。振り返りを自動で作る相手と週を探し、1 人ずつ Tasks に積む。

    積めなかった人がいれば、残りを積み終えてから 500 を返す（Scheduler のログに失敗が残る）。
    その人は 1 時間後の次の回でもう一度見つかる。TASKS_QUEUE が空なら探すだけ。
    """
    done = await dispatch_due_reviews(session, queue, datetime.now(UTC))
    if done.failed:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"could not enqueue {len(done.failed)} of {len(done.due)} reviews",
        )
    return DispatchOut(
        reviews=[DueReviewOut(user_id=d.user_id, period_start=d.period_start) for d in done.due]
    )


@router.post("/reviews/users/{user_id}/weeks/{period_start}")
async def create_review_for_user(
    user_id: int,
    period_start: date,
    session: DbSession,
    writer: ReviewWriterDep,
    checker: LineCheckerDep,
) -> AutoReviewOut:
    """Tasks が 1 人ずつ呼ぶ。探したときの週（period_start に始まる 7 日間）の振り返りを作る。

    2xx 以外を返すと Tasks がやり直す。作れない相手（アカウントを消した、ゲスト、心拍の
    設定がない、今の週が period_start でなくなった）はやり直しても変わらないので 200 の
    skipped にする。
    """
    done = await create_for_user(session, user_id, period_start, writer, checker)
    logger.info(
        "internal: weekly review for user %s, week of %s: %s",
        user_id,
        period_start,
        done.result.value,
    )
    return AutoReviewOut(result=done.result, review_id=done.review_id)
