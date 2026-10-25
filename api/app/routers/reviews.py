from fastapi import APIRouter, HTTPException, Response, status

from app.routers.deps import CurrentUser, DbSession
from app.schemas.reviews import WeeklyReviewOut
from app.services.reviews import HeartRateSettingsMissingError, create_review, current_review

router = APIRouter(prefix="/reviews", tags=["reviews"])


@router.post(
    "",
    response_model=WeeklyReviewOut,
    status_code=status.HTTP_201_CREATED,
    responses={
        status.HTTP_200_OK: {"model": WeeklyReviewOut, "description": "その週の振り返りはもうある"},
        status.HTTP_403_FORBIDDEN: {"description": "ゲスト（デモの利用者）は作れない"},
        status.HTTP_409_CONFLICT: {"description": "最大心拍か安静時心拍が未設定"},
    },
)
async def add_review(user: CurrentUser, session: DbSession, response: Response) -> WeeklyReviewOut:
    """今の振り返りの週の振り返りを作る。週は、今日以前でいちばん近い振り返りの曜日の
    前日までの 7 日間（利用者のタイムゾーン）。

    その週の振り返りがもうあれば、作り直さずにそれを 200 で返す。後から届いた記録も
    入れない。今は定型のセリフで作る。
    """
    if user.is_demo:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "guests cannot create reviews")
    try:
        review, created = await create_review(session, user)
    except HeartRateSettingsMissingError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, "set max and resting heart rate first") from e
    if not created:
        response.status_code = status.HTTP_200_OK
    return review


@router.get(
    "/current",
    response_model=WeeklyReviewOut,
    responses={status.HTTP_404_NOT_FOUND: {"description": "今の週の振り返りはまだない"}},
)
async def read_current_review(user: CurrentUser, session: DbSession) -> WeeklyReviewOut:
    """今の振り返りの週の振り返り。週の決め方は POST /reviews と同じ。"""
    review = await current_review(session, user)
    if review is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return review
