from datetime import date, datetime
from typing import Annotated, Self

from pydantic import AfterValidator, BaseModel, ConfigDict, StringConstraints, model_validator

from app.domain.label import MAX_LABEL_WIDTH, display_width

# 前後の空白は落とす。空白だけの本文は空として弾く
NoteBody = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


def _label(value: str | None) -> str | None:
    """前後の空白を落とし、空ならラベルなし（None）。幅は半角 1、全角 2 で 12 まで。"""
    if value is None:
        return None
    value = value.strip()
    if value == "":
        return None
    if display_width(value) > MAX_LABEL_WIDTH:
        raise ValueError(f"label is wider than {MAX_LABEL_WIDTH} (full-width counts as 2)")
    return value


NoteLabel = Annotated[str | None, AfterValidator(_label)]


class NoteIn(BaseModel):
    """POST /notes の本文。未来の日付かどうかは、利用者のタイムゾーンを知る service で確かめる。"""

    date: date
    body: NoteBody
    label: NoteLabel = None


class NoteUpdate(BaseModel):
    """PATCH /notes/{id} の本文。日付は変えない。間違えたら消して書き直す。

    送った項目だけを直す。label を送らなければ今のまま、null か空を送ると消す。
    """

    body: NoteBody | None = None
    label: NoteLabel = None

    @model_validator(mode="after")
    def _body_is_not_null(self) -> Self:
        # 本文は必ずある。label の null は「ラベルを消す」だが、body の null は受けない
        if "body" in self.model_fields_set and self.body is None:
            raise ValueError("body cannot be null")
        return self


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
