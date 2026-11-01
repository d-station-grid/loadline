"""Cloud Scheduler と Cloud Tasks だけが呼ぶ窓口。

利用者の画面からは使わないので、OpenAPI（web の型）には載せない。
"""

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.core.internal_auth import require_internal_caller
from app.routers.deps import DbSession, ReviewWriterDep
from app.services.auto_reviews import (
    AutoReviewResult,
    UserNotFoundError,
    create_for_user,
    due_user_ids,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/internal",
    dependencies=[Depends(require_internal_caller)],
    include_in_schema=False,
)


class DispatchOut(BaseModel):
    user_ids: list[int]


class AutoReviewOut(BaseModel):
    result: AutoReviewResult
    review_id: int | None


@router.post("/reviews/dispatch")
async def dispatch_reviews(session: DbSession) -> DispatchOut:
    """Scheduler が 1 時間おきに呼ぶ。振り返りを自動で作る相手を探す。

    Tasks に積むのは次の PR で足す。今は見つけた相手をログに出して返すだけ。
    """
    user_ids = await due_user_ids(session, datetime.now(UTC))
    logger.info("internal: %d users are due for a weekly review: %s", len(user_ids), user_ids)
    return DispatchOut(user_ids=user_ids)


@router.post("/reviews/users/{user_id}")
async def create_review_for_user(
    user_id: int, session: DbSession, writer: ReviewWriterDep
) -> AutoReviewOut:
    """Tasks が 1 人ずつ呼ぶ。その人の今の週の振り返りを作る。

    2xx 以外を返すと Tasks がやり直す。作れない相手（ゲスト、心拍の設定がない）は
    やり直しても変わらないので 200 の skipped にする。
    """
    try:
        done = await create_for_user(session, user_id, writer)
    except UserNotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND) from e
    logger.info("internal: weekly review for user %s: %s", user_id, done.result.value)
    return AutoReviewOut(result=done.result, review_id=done.review_id)
