from fastapi import APIRouter, HTTPException, Response, status

from app.routers.deps import (
    AudioStoreDep,
    CurrentUser,
    DbSession,
    LineCheckerDep,
    ReviewWriterDep,
    VoiceDep,
    WritableUser,
)
from app.schemas.reviews import SelectionIn, WeeklyReviewOut
from app.services.reviews import (
    HeartRateSettingsMissingError,
    ReviewClosedError,
    ReviewNotFoundError,
    create_review,
    current_review,
    select_option,
)

router = APIRouter(prefix="/reviews", tags=["reviews"])


@router.post(
    "",
    response_model=WeeklyReviewOut,
    status_code=status.HTTP_201_CREATED,
    responses={
        status.HTTP_200_OK: {
            "model": WeeklyReviewOut,
            "description": "その週の週次レビューはもうある",
        },
        status.HTTP_403_FORBIDDEN: {"description": "ゲスト（デモの利用者）は作れない"},
        status.HTTP_409_CONFLICT: {"description": "最大心拍か安静時心拍が未設定"},
    },
)
async def add_review(
    user: WritableUser,
    session: DbSession,
    writer: ReviewWriterDep,
    checker: LineCheckerDep,
    voice: VoiceDep,
    audio: AudioStoreDep,
    response: Response,
) -> WeeklyReviewOut:
    """今の週の週次レビューを作る。週は、今日以前でいちばん近い週次レビューの曜日の
    前日までの 7 日間（利用者のタイムゾーン）。

    その週の週次レビューがもうあれば、作り直さずにそれを 200 で返す。後から届いた記録も
    入れない。GEMINI_PROJECT と TYPESAFE_API_KEY が設定されていればセリフと選択肢を
    Gemini が書き、Jev で話してよいと確かめられたときだけその文にする。書けない、
    引っかかった、確かめられなかった（時間切れも）ときは定型にする。設定がなければ
    定型だけ。どちらだったかは is_fallback で分かる。

    TTS_URL と AUDIO_BUCKET が設定されていれば、セリフを声にして audio_url を付ける。
    声を作れなかったときは audio_url が null。
    """
    try:
        review, created = await create_review(
            session, user, writer, checker, voice=voice, audio=audio
        )
    except HeartRateSettingsMissingError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, "set max and resting heart rate first") from e
    if not created:
        response.status_code = status.HTTP_200_OK
    return review


@router.get(
    "/current",
    response_model=WeeklyReviewOut,
    responses={
        status.HTTP_404_NOT_FOUND: {
            "description": (
                "今の週の週次レビューはまだない（ゲストは、デモの週次レビューがひとつもない）"
            )
        }
    },
)
async def read_current_review(
    user: CurrentUser, session: DbSession, audio: AudioStoreDep
) -> WeeklyReviewOut:
    """今の週の週次レビュー。週の決め方は POST /reviews と同じ。

    ゲスト（デモの利用者）には、今の週ではなく、いちばん新しい期間の週次レビューを返す。
    デモデータは日付が動かず、今の週の週次レビューはないため。
    """
    review = await current_review(session, user, audio=audio)
    if review is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return review


@router.put(
    "/{review_id}/selection",
    response_model=WeeklyReviewOut,
    responses={
        status.HTTP_403_FORBIDDEN: {"description": "ゲスト（デモの利用者）は選べない"},
        status.HTTP_404_NOT_FOUND: {
            "description": "週次レビューか、その週次レビューの選択肢がない",
        },
        status.HTTP_409_CONFLICT: {"description": "今の週の週次レビューではない"},
    },
)
async def put_selection(
    review_id: int,
    body: SelectionIn,
    user: WritableUser,
    session: DbSession,
    audio: AudioStoreDep,
) -> WeeklyReviewOut:
    """週次レビューの選択肢を 1 つ選ぶ。選び直すと、前に選んだものは外れる。

    選び直せるのは今の週の週次レビューだけ。過ぎた週の選択は、次の週の週次レビューの材料に
    使うので変えない。
    """
    try:
        return await select_option(session, user, review_id, body.option_id, audio=audio)
    except ReviewNotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND) from e
    except ReviewClosedError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, "only the current review can change") from e
