import hashlib
import secrets
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import IngestToken, User


def _digest(token: str) -> str:
    """DB に置くのはこのハッシュだけ。トークンそのものは保存しない。"""
    return hashlib.sha256(token.encode()).hexdigest()


async def issue_token(session: AsyncSession, user_id: int) -> tuple[str, IngestToken]:
    """新しいトークンを発行し、それまで有効だったものは無効にする。

    平文のトークンは戻り値でしか手に入らない。設定画面はこのとき 1 回だけ表示する。
    """
    # 同じ利用者の発行を直列にする。連打や複数タブで 2 本同時に走ると、
    # 互いの新しいトークンを無効にできず、有効なものが 2 つ残るため
    await session.execute(select(User.id).where(User.id == user_id).with_for_update())
    now = datetime.now(UTC)
    active = await session.scalars(
        select(IngestToken).where(IngestToken.user_id == user_id, IngestToken.revoked_at.is_(None))
    )
    for old in active:
        old.revoked_at = now
    token = secrets.token_urlsafe(32)
    row = IngestToken(user_id=user_id, token_digest=_digest(token), last_four=token[-4:])
    session.add(row)
    await session.commit()
    return token, row


async def current_token(session: AsyncSession, user_id: int) -> IngestToken | None:
    """いま有効なトークンの行。設定画面で「…abcd」と出すために使う。"""
    return await session.scalar(
        select(IngestToken).where(IngestToken.user_id == user_id, IngestToken.revoked_at.is_(None))
    )


async def find_user_id_by_token(session: AsyncSession, token: str) -> int | None:
    """有効なトークンなら持ち主の user_id を返し、last_used_at を更新する。それ以外は None。"""
    row = await session.scalar(
        select(IngestToken).where(
            IngestToken.token_digest == _digest(token), IngestToken.revoked_at.is_(None)
        )
    )
    if row is None:
        return None
    row.last_used_at = datetime.now(UTC)
    await session.commit()
    return row.user_id
