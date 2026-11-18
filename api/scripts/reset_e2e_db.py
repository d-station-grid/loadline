"""通しのテスト（e2e/）用の DB を、空の表から作り直す。

使い方（api/ で。DATABASE_URL は e2e 用の DB を指す）:
  DATABASE_URL=postgresql+asyncpg://loadline:loadline@localhost:5432/loadline_e2e \
    uv run python -m scripts.reset_e2e_db

表をすべて消すので、DB の名前が _e2e で終わるときだけ動く。開発用の DB には触らない。
DB がなければ作る。表は alembic で作り、本番と同じ形にする。デモデータは
scripts.seed_demo で別に入れる。
"""

import asyncio
import subprocess
import sys

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings

SUFFIX = "_e2e"


async def reset() -> None:
    url = make_url(get_settings().database_url)
    name = url.database or ""
    if not name.endswith(SUFFIX):
        sys.exit(f"refusing to reset {name!r}: the database name must end with {SUFFIX}")

    # CREATE DATABASE はトランザクションの中では打てないので AUTOCOMMIT で。
    # つなぐ先は Postgres に必ずある postgres の DB
    admin = create_async_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    async with admin.connect() as conn:
        exists = await conn.scalar(
            text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": name}
        )
        if not exists:
            await conn.execute(text(f'CREATE DATABASE "{name}"'))
    await admin.dispose()

    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
    await engine.dispose()


def main() -> None:
    asyncio.run(reset())
    # alembic は同じ DATABASE_URL（環境変数）を読む
    subprocess.run(["alembic", "upgrade", "head"], check=True)


if __name__ == "__main__":
    main()
