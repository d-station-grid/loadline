from datetime import date, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

# 前後の空白は落とす。空白だけの本文は空として弾く
NoteBody = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class NoteIn(BaseModel):
    """POST /notes の本文。未来の日付かどうかは、利用者のタイムゾーンを知る router で確かめる。"""

    date: date
    body: NoteBody


class NoteUpdate(BaseModel):
    """PATCH /notes/{id} の本文。日付は変えない。間違えたら消して書き直す。"""

    body: NoteBody


class NoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    date: date
    label: str | None
    body: str
    created_at: datetime
    updated_at: datetime


class NoteList(BaseModel):
    items: list[NoteOut]
