from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

from app.domain.situation import Situation
from app.models.weekly_review import ReviewStatus


class ReviewOptionOut(BaseModel):
    """その週の過ごし方の選択肢。label はボタンの文字、description はその下の 1 文。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    position: int
    label: str
    description: str
    selected_at: datetime | None


class WeeklyReviewOut(BaseModel):
    """週に 1 回の振り返り。期間は利用者のタイムゾーンでの日付で、両端を含む。

    script はアバターのセリフで、字幕にも使う。is_fallback が true なら人が書いた定型。
    options は position の順。音声は声にする機能で足す。
    """

    id: int
    period_start: date
    period_end: date
    situation: Situation
    script: str
    status: ReviewStatus
    is_fallback: bool
    created_at: datetime
    options: list[ReviewOptionOut]
