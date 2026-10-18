from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Note, User


def today_for(user: User) -> date:
    """利用者のタイムゾーンでの今日。"""
    return datetime.now(ZoneInfo(user.timezone)).date()


async def create_note(session: AsyncSession, user_id: int, day: date, body: str) -> Note | None:
    """メモを 1 件作る。その日にもう書いてあれば何もせず None。

    先に探してから入れると、同時に 2 回届いたときに一意制約の例外になる。
    ON CONFLICT DO NOTHING なら、どちらの順でも 1 件だけ入る。
    """
    stmt = (
        insert(Note)
        .values(user_id=user_id, date=day, body=body)
        .on_conflict_do_nothing(index_elements=[Note.user_id, Note.date])
        .returning(Note)
    )
    note = await session.scalar(stmt)
    await session.commit()
    return note


async def list_notes(
    session: AsyncSession, user_id: int, since: date | None = None, until: date | None = None
) -> list[Note]:
    """本人のメモを新しい日付から。since 以上、until 未満で絞る。"""
    stmt = select(Note).where(Note.user_id == user_id)
    if since is not None:
        stmt = stmt.where(Note.date >= since)
    if until is not None:
        stmt = stmt.where(Note.date < until)
    stmt = stmt.order_by(Note.date.desc())
    return list(await session.scalars(stmt))
