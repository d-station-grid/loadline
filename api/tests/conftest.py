from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from app.core.config import get_settings
from app.core.db import get_session
from app.main import app
from app.models import Base
from tests.factories import BaseFactory


def _test_url() -> URL:
    """DATABASE_URL の DB 名に _test を付けたもの。開発用の DB にはテストで触らない。"""
    url = make_url(get_settings().database_url)
    return url.set(database=f"{url.database}_test")


@pytest.fixture(scope="session")
async def engine() -> AsyncIterator[AsyncEngine]:
    """テスト全体で 1 つのエンジン。最初にテスト用 DB を用意し、表を作り直す。"""
    url = _test_url()

    # CREATE DATABASE はトランザクションの中では打てないので AUTOCOMMIT で
    admin = create_async_engine(get_settings().database_url, isolation_level="AUTOCOMMIT")
    async with admin.connect() as conn:
        exists = await conn.scalar(
            text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": url.database}
        )
        if not exists:
            await conn.execute(text(f'CREATE DATABASE "{url.database}"'))
    await admin.dispose()

    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """テストごとにトランザクションを開き、終わりに巻き戻す。中の commit は savepoint になる。"""
    async with engine.connect() as conn:
        await conn.begin()
        async with AsyncSession(
            bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
        ) as s:
            # factory もこのセッションに保存する
            BaseFactory.__async_session__ = s
            yield s
            BaseFactory.__async_session__ = None
        await conn.rollback()


@pytest.fixture
async def client(session: AsyncSession) -> AsyncIterator[AsyncClient]:
    """API の get_session をテスト用のセッションに差し替えたクライアント。"""

    async def _override() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = _override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


class QueryCounter:
    """発行された SQL を数える。数えるのは reset() の後だけ。"""

    def __init__(self) -> None:
        self.statements: list[str] = []

    @property
    def count(self) -> int:
        return len(self.statements)

    def reset(self) -> None:
        self.statements.clear()


@pytest.fixture
def queries(engine: AsyncEngine) -> Iterator[QueryCounter]:
    """このテストの間に DB へ送った SQL。executemany でまとめて送ったものは 1 回と数える。"""
    counter = QueryCounter()

    def _count(_conn: Any, _cursor: Any, statement: str, *_args: Any) -> None:
        counter.statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", _count)
    yield counter
    event.remove(engine.sync_engine, "before_cursor_execute", _count)
