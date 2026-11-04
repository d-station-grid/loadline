from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Identity
from app.models import DeletedAccount, User


class AccountDeletedError(Exception):
    """アカウントを消した人の ID トークン。期限まで検証を通るので、ここで止める。"""


async def get_or_create_user(session: AsyncSession, identity: Identity) -> User:
    """firebase_uid で探し、なければ作る。初回ログインで行ができる。

    アカウントを消した人の uid なら作らずに AccountDeletedError を上げる。行がある人は
    消していないので、見るのは行がないときだけ。
    """
    user = await session.scalar(select(User).where(User.firebase_uid == identity.uid))
    if user is not None:
        return user
    if await session.get(DeletedAccount, identity.uid) is not None:
        raise AccountDeletedError

    user = User(firebase_uid=identity.uid, email=identity.email)
    session.add(user)
    try:
        await session.commit()
    except IntegrityError:
        # 同じ人の初回ログインが同時に 2 つ走ると unique で片方が落ちる。先に入った行を返す
        await session.rollback()
        existing = await session.scalar(select(User).where(User.firebase_uid == identity.uid))
        assert existing is not None
        return existing
    return user
