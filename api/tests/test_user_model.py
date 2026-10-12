from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User


async def _count_users(session: AsyncSession) -> int:
    return await session.scalar(select(func.count()).select_from(User)) or 0


async def test_insert_user(session: AsyncSession) -> None:
    assert await _count_users(session) == 0

    session.add(User(firebase_uid="uid-1", email="one@example.com"))
    await session.commit()

    assert await _count_users(session) == 1


async def test_insert_user_starts_empty_again(session: AsyncSession) -> None:
    # 前のテストの commit は巻き戻されているので、また空から始まる
    assert await _count_users(session) == 0

    session.add(User(firebase_uid="uid-1", email="one@example.com"))
    await session.commit()

    assert await _count_users(session) == 1
