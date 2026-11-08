"""アカウントとデータを消す。

DB は users の行を 1 つ消せば、ほかの表の本人の行は外部キーの CASCADE で消える。
Cloud Storage の音声と Firebase の利用者も消すので、どれかだけ消えた状態を残さないよう、
DB は flush だけして音声、Firebase の順に消し、できたら commit する。途中で失敗したら
巻き戻し、やり直せるようにする。Firebase を最後にするのは、先に消すとログインできず、
本人がやり直せなくなるため。

消した人の uid は deleted_accounts に 1 日だけ残す。出してある ID トークンが期限（1 時間）
まで検証を通るので、そのトークンで行を作り直させない。
"""

from datetime import datetime, timedelta
from typing import Protocol

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DeletedAccount, User
from app.services.audio import AudioStore, user_audio_prefix

# ID トークンの期限（1 時間）に、時計のずれと届くのが遅れたリクエストの分を足す
KEEP_DELETED_UID = timedelta(days=1)


class AccountDeleteError(Exception):
    """音声か Firebase の利用者を消せなかった。"""


class AccountDeleter(Protocol):
    """Firebase の利用者を消す。adapter の FirebaseAccountDeleter が実体。

    相手がもういなければ、消えたものとして返る。消せなければ AccountDeleteError を上げる。
    """

    async def delete(self, uid: str) -> None: ...


async def delete_account(
    session: AsyncSession,
    user: User,
    deleter: AccountDeleter,
    audio: AudioStore | None = None,
) -> None:
    """本人の行をすべて消し、音声と Firebase の利用者も消す。

    音声か Firebase で失敗したら DB を巻き戻して例外を上げる。DB と Firebase の利用者は
    残るので、やり直せる。音声で失敗したときは一部のファイルが消えていることがあり、その
    振り返りは音声の URL を開いても再生できない。
    firebase_uid がない人は Firebase を呼ばず、uid も残さない。audio がない（声にしない
    設定）なら音声は消さない。
    """
    uid = user.firebase_uid
    prefix = user_audio_prefix(user.id)
    await session.delete(user)
    if uid is not None:
        session.add(DeletedAccount(firebase_uid=uid))
    await session.flush()
    try:
        if audio is not None:
            await audio.delete_all(prefix)
        if uid is not None:
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
