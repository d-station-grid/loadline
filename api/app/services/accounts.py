"""アカウントとデータを消す。

DB は users の行を 1 つ消せば、ほかの表の本人の行は外部キーの CASCADE で消える。
Firebase の利用者も消すので、どちらかだけ消えた状態を残さないよう、DB は flush だけして
Firebase を消し、できたら commit する。Firebase で失敗したら巻き戻し、やり直せるようにする。
"""

from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User


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
    firebase_uid がない人は Firebase を呼ばない。
    """
    uid = user.firebase_uid
    await session.delete(user)
    await session.flush()
    if uid is not None:
        try:
            await deleter.delete(uid)
        except Exception:
            await session.rollback()
            raise
    await session.commit()
