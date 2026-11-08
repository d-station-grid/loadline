from fastapi import APIRouter, HTTPException, status

from app.routers.deps import AccountDeleterDep, AudioStoreDep, DbSession, WritableUser
from app.services.accounts import AccountDeleteError, delete_account

router = APIRouter(prefix="/me", tags=["me"])


@router.delete(
    "",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        status.HTTP_403_FORBIDDEN: {"description": "ゲスト（デモの利用者）は消せない"},
        status.HTTP_502_BAD_GATEWAY: {
            "description": "音声か Firebase の利用者を消せなかった。記録とログインは残るので、"
            "やり直せる"
        },
    },
)
async def delete_me(
    user: WritableUser,
    session: DbSession,
    deleter: AccountDeleterDep,
    audio: AudioStoreDep,
) -> None:
    """ログイン中の本人を消す。記録、メモ、振り返りとその音声、取り込み用トークン、
    Firebase の利用者。

    音声か Firebase の利用者を消せなければ、記録とログインを残して 502 を返す。もう一度
    呼べばやり直せる。
    消したあとは、同じ ID トークンでも 401 になる。
    """
    try:
        await delete_account(session, user, deleter, audio)
    except AccountDeleteError as e:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "could not delete the account, try again"
        ) from e
