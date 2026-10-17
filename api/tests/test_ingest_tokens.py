import hashlib

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import IngestToken
from app.services.ingest_tokens import current_token, find_user_id_by_token, issue_token
from tests.factories import UserFactory


async def test_issue_stores_only_digest(session: AsyncSession) -> None:
    user = await UserFactory.create_async()

    token, row = await issue_token(session, user.id)

    assert row.token_digest == hashlib.sha256(token.encode()).hexdigest()
    assert row.last_four == token[-4:]
    assert token not in row.token_digest


async def test_reissue_revokes_the_old_token(session: AsyncSession) -> None:
    user = await UserFactory.create_async()
    old_token, old_row = await issue_token(session, user.id)

    new_token, new_row = await issue_token(session, user.id)

    assert old_row.revoked_at is not None
    assert new_row.revoked_at is None
    assert await find_user_id_by_token(session, old_token) is None
    assert await find_user_id_by_token(session, new_token) == user.id
    current = await current_token(session, user.id)
    assert current is not None
    assert current.id == new_row.id


async def test_find_user_updates_last_used_at(session: AsyncSession) -> None:
    user = await UserFactory.create_async()
    token, row = await issue_token(session, user.id)
    assert row.last_used_at is None

    assert await find_user_id_by_token(session, token) == user.id

    assert row.last_used_at is not None


async def test_unknown_token_is_none(session: AsyncSession) -> None:
    user = await UserFactory.create_async()
    await issue_token(session, user.id)

    assert await find_user_id_by_token(session, "not-a-token") is None
    assert await session.scalar(select(func.count()).select_from(IngestToken)) == 1
