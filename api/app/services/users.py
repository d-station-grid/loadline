from datetime import date
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Identity
from app.domain.calendar import today_in
from app.models import DeletedAccount, User, Workout


class AccountDeletedError(Exception):
    """アカウントを消した人の ID トークン。期限まで検証を通るので、ここで止める。"""


class DemoUnavailableError(Exception):
    """ゲストが入ったが、デモの利用者がまだいない。seed で入れる前の環境。"""


async def get_demo_user(session: AsyncSession) -> User:
    """ゲストに見せるデモの利用者。匿名ログインの人は全員この 1 人として扱い、行を作らない。"""
    user = await session.scalar(select(User).where(User.is_demo.is_(True)))
    if user is None:
        raise DemoUnavailableError
    return user


async def today_of(session: AsyncSession, user: User) -> date:
    """その利用者にとっての今日（利用者のタイムゾーン）。「直近 N 週」の終わりに使う。

    デモの利用者は、最後のワークアウトの日を今日とする。デモデータは日付が動かないので、
    今の日付で切ると「直近 N 週」が日が経つほど空になるため。記録がなければ今日。
    """
    tz = ZoneInfo(user.timezone)
    if user.is_demo:
        last = await session.scalar(
            select(func.max(Workout.started_at)).where(Workout.user_id == user.id)
        )
        if last is not None:
            return last.astimezone(tz).date()
    return today_in(tz)


async def get_or_create_user(session: AsyncSession, identity: Identity) -> User:
    """firebase_uid で探し、なければ作る。初回ログインで行ができる。

    アカウントを消した人の uid なら作らずに AccountDeletedError を上げる。行がある人は
    消していないので、見るのは行がないときだけ。

    匿名ログイン（ゲスト）はデモの利用者を返す。いなければ DemoUnavailableError。
    """
    if identity.is_anonymous:
        return await get_demo_user(session)
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
