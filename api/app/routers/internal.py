"""Cloud Scheduler と Cloud Tasks だけが呼ぶ窓口。

利用者の画面からは使わないので、OpenAPI（web の型）には載せない。
"""

import logging
from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.core.internal_auth import require_internal_caller
from app.routers.deps import DbSession, ReviewWriterDep
from app.services.auto_reviews import (
    AutoReviewResult,
    UserNotFoundError,
    create_for_user,
    due_reviews,
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
async def dispatch_reviews(session: DbSession) -> DispatchOut:
    """Scheduler が 1 時間おきに呼ぶ。振り返りを自動で作る相手と週を探す。

    Tasks に積むのは次の PR で足す。今は見つけた相手をログに出して返すだけ。
    """
    due = await due_reviews(session, datetime.now(UTC))
    logger.info("internal: %d users are due for a weekly review: %s", len(due), due)
    return DispatchOut(
        reviews=[DueReviewOut(user_id=d.user_id, period_start=d.period_start) for d in due]
    )


@router.post("/reviews/users/{user_id}/weeks/{period_start}")
async def create_review_for_user(
    user_id: int, period_start: date, session: DbSession, writer: ReviewWriterDep
) -> AutoReviewOut:
    """Tasks が 1 人ずつ呼ぶ。探したときの週（period_start に始まる 7 日間）の振り返りを作る。

    2xx 以外を返すと Tasks がやり直す。作れない相手（ゲスト、心拍の設定がない、今の週が
    period_start でなくなった）はやり直しても変わらないので 200 の skipped にする。
    """
    try:
        done = await create_for_user(session, user_id, period_start, writer)
    except UserNotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND) from e
    logger.info(
        "internal: weekly review for user %s, week of %s: %s",
        user_id,
        period_start,
        done.result.value,
    )
    return AutoReviewOut(result=done.result, review_id=done.review_id)
