from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings


@lru_cache
def get_engine() -> AsyncEngine:
    """エンジンはプロセスで 1 つ。初めて呼ばれたときに作る。

    pool_pre_ping: 接続を使う前に 1 回確かめ、切れていれば張り直す。
    Neon は使われない接続をしばらくすると閉じるので、時間を空けた次のリクエストが
    プールの古い接続で「connection is closed」になるのを防ぐ（#12）。
    """
    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


@lru_cache
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI の依存。リクエストごとにセッションを 1 つ開き、終わったら閉じる。"""
    async with get_session_factory()() as session:
        yield session
