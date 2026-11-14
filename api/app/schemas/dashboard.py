from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

from app.domain.situation import Form
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


class Changes(BaseModel):
    """カードに添える差。体力・疲労・余力は until の値 − その 7 日前の値。

    VO2max は期間の最新の測定 − その測定日の 28 日前かそれより前の最後の測定。
    vo2max_since は比べた測定の日。測定が空くと 28 日より前になるので、画面は「4 週前」と
    言わず、この日を書く。
    比べる値がなければ None（心拍の設定がない、期間に測定がない、前の測定がない）。
    """

    fitness: float | None
    fatigue: float | None
    headroom: float | None
    vo2max: float | None
    vo2max_since: date | None


class ZoneWeek(BaseModel):
    """7 日ぶん（start から end まで、両端を含む）の強度ごとの時間。

    zones は心拍の分かる回だけの合計。workouts_without_zones は足せなかった回の数。
    """

    start: date
    end: date
    zones: ZoneSeconds
    workouts_without_zones: int


class Totals(BaseModel):
    """期間（start から end まで、両端を含む）の合計。

    load は負荷の分かる回だけの合計で、回があるのに 1 回も分からなければ None。
    load_per_workout は 負荷の合計 ÷ 負荷の分かる回の数。workouts_without_load は外した回の数。
    """

    start: date
    end: date
    workouts: int
    total_sec: int
    load: float | None
    load_per_workout: float | None
    workouts_without_load: int


class Dashboard(BaseModel):
    """ダッシュボードの 1 画面ぶん。日付は利用者のタイムゾーンで区切る。

    days は全種目で計算する（種目で絞ると疲労を低く見積もるため）。sport で絞るのは
    zones、workouts、zone_weeks、totals、previous_totals だけ。最大心拍か安静時心拍が
    未設定なら、負荷が出ないので days は空で、needs_heart_rate_settings が true。

    changes と form も全種目。form は until の余力の区分（週次レビューの週の判定と同じ境目）で、
    days が空なら None。zone_weeks は until から 7 日ずつ区切った強度の時間で、古い順。
    境目がそろわなければ None。totals は期間の合計、previous_totals は since の前の同じ
    日数の合計。last_received_at は Health Auto Export からの取り込みが最後に成功した日時で、
    成功したことがなければ None（デモの利用者は常に None）。新しい記録が保存されたとは限らない
    （同じ記録が届き直しただけでも進む）。
    """

    since: date
    until: date
    sport: Sport
    needs_heart_rate_settings: bool
    days: list[DayPoint]
    vo2max: list[Vo2maxPoint]
    zones: ZoneSeconds | None
    workouts: list[WorkoutPoint]
    changes: Changes
    form: Form | None
    zone_weeks: list[ZoneWeek] | None
    totals: Totals
    previous_totals: Totals
    last_received_at: datetime | None
