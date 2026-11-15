from fastapi import APIRouter, status

from app.routers.deps import CurrentIdentity, DbSession, GuestLanguage, resolve_user
from app.schemas.user import LoginIn, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/login",
    response_model=UserOut,
    responses={
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "description": "ゲスト（匿名ログイン）で入ったが、デモデータがまだ入っていない"
        }
    },
)
async def login(
    identity: CurrentIdentity,
    session: DbSession,
    body: LoginIn | None = None,
    guest_language: GuestLanguage = None,
) -> UserOut:
    """ID トークンで本人を確かめ、初回なら利用者の行を作って返す。

    初回は本文の timezone と language（ブラウザのタイムゾーンと言語）を利用者の設定にする。
    空や知らない値なら既定値。2 回目からは本文を見ない。アカウントを消した人のトークンは
    401（行を作り直さない）。ゲスト（Firebase の匿名ログイン）は行を作らず、X-Guest-Language の
    言語のデモの利用者を返す（ほかの窓口と同じ。本文の language はゲストには使わない）。
    """
    user = await resolve_user(
        session,
        identity,
        body.timezone if body else None,
        body.language if body else None,
        guest_language,
    )
    return UserOut.model_validate(user)
