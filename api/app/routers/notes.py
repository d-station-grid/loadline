from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Response, status

from app.routers.deps import CurrentUser, DbSession
from app.schemas.notes import NoteIn, NoteList, NoteOut, NoteUpdate
from app.services.notes import create_note, delete_note, list_notes, today_for, update_note

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
        # 422 は上書きしない。FastAPI が付ける検証エラーの形を、生成する型に残すため
        status.HTTP_400_BAD_REQUEST: {"description": "未来の日付"},
        status.HTTP_409_CONFLICT: {"description": "その日のメモはもうある"},
    },
)
async def add_note(body: NoteIn, user: CurrentUser, session: DbSession) -> NoteOut:
    """メモを 1 件書く。走らなかった日にも書ける。1 日 1 件で、その日にもうあれば 409。"""
    # 今日の判定は利用者のタイムゾーンで。日付の比較はここでやる
    if body.date > today_for(user):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "date is in the future")
    note = await create_note(session, user.id, body.date, body.body)
    if note is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "a note for this date already exists")
    return NoteOut.model_validate(note)


# 他人のメモも、ないメモも 404。どちらかは見分けさせない
NOT_FOUND: dict[int | str, dict[str, Any]] = {
    status.HTTP_404_NOT_FOUND: {"description": "本人のメモにない"}
}


@router.patch("/{note_id}", response_model=NoteOut, responses=NOT_FOUND)
async def edit_note(
    note_id: int, body: NoteUpdate, user: CurrentUser, session: DbSession
) -> NoteOut:
    """メモの本文を直す。日付は変えない。"""
    note = await update_note(session, user.id, note_id, body.body)
    if note is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return NoteOut.model_validate(note)


@router.delete("/{note_id}", status_code=status.HTTP_204_NO_CONTENT, responses=NOT_FOUND)
async def remove_note(note_id: int, user: CurrentUser, session: DbSession) -> Response:
    """メモを消す。消した日には、また新しく書ける。"""
    if not await delete_note(session, user.id, note_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
