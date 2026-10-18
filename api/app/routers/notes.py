from datetime import date
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from app.routers.deps import CurrentUser, DbSession
from app.schemas.notes import NoteIn, NoteList, NoteOut
from app.services.notes import create_note, list_notes, today_for

router = APIRouter(prefix="/notes", tags=["notes"])


@router.get("", response_model=NoteList)
async def read_notes(
    user: CurrentUser,
    session: DbSession,
    since: Annotated[date | None, Query()] = None,
    until: Annotated[date | None, Query()] = None,
) -> NoteList:
    """本人のメモを新しい日付から。since 以上、until 未満。"""
    rows = await list_notes(session, user.id, since=since, until=until)
    return NoteList(items=[NoteOut.model_validate(r) for r in rows])


@router.post(
    "",
    response_model=NoteOut,
    status_code=status.HTTP_201_CREATED,
    responses={
        status.HTTP_409_CONFLICT: {"description": "その日のメモはもうある"},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"description": "未来の日付、または本文が不正"},
    },
)
async def add_note(body: NoteIn, user: CurrentUser, session: DbSession) -> NoteOut:
    """メモを 1 件書く。走らなかった日にも書ける。1 日 1 件で、その日にもうあれば 409。"""
    # 今日の判定は利用者のタイムゾーンで。日付の比較はここでやる
    if body.date > today_for(user):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "date is in the future")
    note = await create_note(session, user.id, body.date, body.body)
    if note is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "a note for this date already exists")
    return NoteOut.model_validate(note)
