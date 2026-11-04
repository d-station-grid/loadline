"""アカウントとデータを消す。

DB は users の行を 1 つ消せば、ほかの表の本人の行は外部キーの CASCADE で消える。
Firebase の利用者も消すので、どちらかだけ消えた状態を残さないよう、DB は flush だけして
Firebase を消し、できたら commit する。Firebase で失敗したら巻き戻し、やり直せるようにする。

消した人の uid は deleted_accounts に 1 日だけ残す。出してある ID トークンが期限（1 時間）
まで検証を通るので、そのトークンで行を作り直させない。
"""

from datetime import datetime, timedelta
from typing import Protocol

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DeletedAccount, User

# ID トークンの期限（1 時間）に、時計のずれと届くのが遅れたリクエストの分を足す
KEEP_DELETED_UID = timedelta(days=1)


class AccountDeleteError(Exception):
    """Firebase の利用者を消せなかった。"""


class AccountDeleter(Protocol):
    """Firebase の利用者を消す。adapter の FirebaseAccountDeleter が実体。

    相手がもういなければ、消えたものとして返る。消せなければ AccountDeleteError を上げる。
    """

    async def delete(self, uid: str) -> None: ...


async def delete_account(session: AsyncSession, user: User, deleter: AccountDeleter) -> None:
    """本人の行をすべて消し、Firebase の利用者も消す。

    Firebase で失敗したら DB を巻き戻して例外を上げる。何も消えていないので、やり直せる。
    firebase_uid がない人は Firebase を呼ばず、uid も残さない。
    """
    uid = user.firebase_uid
    await session.delete(user)
    if uid is not None:
        session.add(DeletedAccount(firebase_uid=uid))
    await session.flush()
    if uid is not None:
        try:
            await deleter.delete(uid)
        except Exception:
            await session.rollback()
            raise
    await session.commit()


async def forget_deleted_accounts(session: AsyncSession, now: datetime) -> int:
    """KEEP_DELETED_UID より前に消した人の uid を消す。消した数を返す。"""
    result = await session.execute(
        delete(DeletedAccount).where(DeletedAccount.deleted_at < now - KEEP_DELETED_UID)
    )
    await session.commit()
    return result.rowcount  # type: ignore[attr-defined,no-any-return]
