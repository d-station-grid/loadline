from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

from app.schemas.workouts import ZoneSeconds

Sport = Literal["all", "run", "ride"]


class DayPoint(BaseModel):
    """その日の終わりの体力・疲労・余力と、その日の負荷。

    load が None の日は、心拍の記録がないワークアウトを含む（負荷を 0 として計算を続けている）。
    """

    day: date
    load: float | None
    fitness: float
    fatigue: float
    headroom: float


class Vo2maxPoint(BaseModel):
    """1 回の測定と、その日を含む直近 30 日の平均。"""

    day: date
    value: float
    average: float


class WorkoutPoint(BaseModel):
    """散布図の 1 点。load は心拍がないと None、high_sec は境目がそろわないと None。"""

    id: int
    sport: str
    started_at: datetime
    day: date
    load: float | None
    high_sec: int | None


class Dashboard(BaseModel):
    """ダッシュボードの 1 画面ぶん。日付は利用者のタイムゾーンで区切る。

    days は全種目で計算する（種目で絞ると疲労を低く見積もるため）。sport で絞るのは
    zones と workouts だけ。最大心拍か安静時心拍が未設定なら、負荷が出ないので days は空で、
    needs_heart_rate_settings が true。
    """

    since: date
    until: date
    sport: Sport
    needs_heart_rate_settings: bool
    days: list[DayPoint]
    vo2max: list[Vo2maxPoint]
    zones: ZoneSeconds | None
    workouts: list[WorkoutPoint]
