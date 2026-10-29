from datetime import date

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.calendar import today_for
from app.models import Note, User


class FutureDateError(ValueError):
    """利用者のタイムゾーンで今日より後の日付。"""


async def create_note(
    session: AsyncSession, user: User, day: date, body: str, label: str | None = None
) -> Note | None:
    """メモを 1 件作る。その日にもう書いてあれば何もせず None。

    今日より後の日付は FutureDateError。今日の判定は利用者のタイムゾーンで。

    先に探してから入れると、同時に 2 回届いたときに一意制約の例外になる。
    ON CONFLICT DO NOTHING なら、どちらの順でも 1 件だけ入る。
    """
    if day > today_for(user.timezone):
        raise FutureDateError(day.isoformat())
    stmt = (
        insert(Note)
        .values(user_id=user.id, date=day, body=body, label=label)
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


async def update_note(
    session: AsyncSession, user_id: int, note_id: int, changes: dict[str, str | None]
) -> Note | None:
    """本人のメモの本文やラベルを直す。他人のメモか、ないメモなら None。

    changes に入っている項目だけを書き換える。空なら何も変えずに今のメモを返す。
    """
    if not changes:
        return await session.scalar(select(Note).where(Note.id == note_id, Note.user_id == user_id))
    stmt = (
        update(Note)
        .where(Note.id == note_id, Note.user_id == user_id)
        .values(**changes)
        .returning(Note)
    )
    note = await session.scalar(stmt)
    await session.commit()
    return note


async def delete_note(session: AsyncSession, user_id: int, note_id: int) -> bool:
    """本人のメモを消す。他人のメモか、ないメモなら False。"""
    stmt = delete(Note).where(Note.id == note_id, Note.user_id == user_id).returning(Note.id)
    deleted = await session.scalar(stmt)
    await session.commit()
    return deleted is not None
