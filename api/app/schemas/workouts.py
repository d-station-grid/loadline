from dataclasses import asdict
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.domain.load import ZoneTimes


class WorkoutSummary(BaseModel):
    """一覧の 1 行。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    sport: str
    started_at: datetime
    ended_at: datetime
    duration_sec: int
    avg_heart_rate: int | None
    max_heart_rate: int | None


class WorkoutList(BaseModel):
    items: list[WorkoutSummary]
    # 絞り込みに使った始まり。weeks で取ったときは api が決めた時刻。続きを取るときは
    # weeks ではなくこれを渡す。日付をまたいで決め直すと、始まりが 1 日進むため
    since: datetime | None


class HeartRateSample(BaseModel):
    """1 分ごとの心拍。"""

    model_config = ConfigDict(from_attributes=True)

    recorded_at: datetime
    min_bpm: int
    avg_bpm: int
    max_bpm: int


class ZoneSeconds(BaseModel):
    """強度ごとの時間（秒）。設定の境目 2 つがそろっているときだけ出す。"""

    low: int
    mid: int
    high: int


def zone_seconds(zones: ZoneTimes | None) -> ZoneSeconds | None:
    """domain の強度ごとの時間を、API の形にする。"""
    return None if zones is None else ZoneSeconds(**asdict(zones))


class WorkoutDetail(WorkoutSummary):
    heart_rates: list[HeartRateSample]
    zones: ZoneSeconds | None
