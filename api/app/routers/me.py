from fastapi import APIRouter, HTTPException, status

from app.routers.deps import AccountDeleterDep, CurrentUser, DbSession
from app.services.accounts import AccountDeleteError, delete_account

router = APIRouter(prefix="/me", tags=["me"])


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def delete_me(user: CurrentUser, session: DbSession, deleter: AccountDeleterDep) -> None:
    """ログイン中の本人を消す。記録、メモ、振り返り、取り込み用トークン、Firebase の利用者。

    Firebase の利用者を消せなければ何も消さずに 502 を返す。もう一度呼べばやり直せる。
    """
    if user.is_demo:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "guests cannot delete the account")
    try:
        await delete_account(session, user, deleter)
    except AccountDeleteError as e:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "could not delete the account, try again"
        ) from e
