from pydantic import BaseModel, Field

# Health Auto Export が送る JSON のうち、使う項目だけを読む。知らない項目は無視する。
# 日時は "2026-09-13 14:10:45 +0900" の文字列で届く。ここでは str のまま受け、services で読む


class Quantity(BaseModel):
    qty: float


class WorkoutSource(BaseModel):
    name: str


class HeartRatePoint(BaseModel):
    """1 分ごとの心拍。キーが大文字なので alias で受ける。"""

    date: str
    min_bpm: float = Field(alias="Min")
    avg_bpm: float = Field(alias="Avg")
    max_bpm: float = Field(alias="Max")


class WorkoutIn(BaseModel):
    id: str
    name: str
    start: str
    end: str
    duration: float
    source: WorkoutSource
    avg_heart_rate: Quantity | None = Field(default=None, alias="avgHeartRate")
    max_heart_rate: Quantity | None = Field(default=None, alias="maxHeartRate")
    heart_rate_data: list[HeartRatePoint] = Field(default_factory=list, alias="heartRateData")


class MetricPoint(BaseModel):
    date: str
    qty: float
    source: str | None = None


class MetricIn(BaseModel):
    name: str
    data: list[MetricPoint] = Field(default_factory=list)


class IngestData(BaseModel):
    workouts: list[WorkoutIn] = Field(default_factory=list)
    metrics: list[MetricIn] = Field(default_factory=list)


class IngestPayload(BaseModel):
    data: IngestData


class IngestResult(BaseModel):
    """受け口が返す集計。Health Auto Export の画面に出るだけなので、数だけ返す。"""

    workouts_added: int = 0
    workouts_updated: int = 0
    workouts_skipped: int = 0
    vo2max_added: int = 0
    vo2max_updated: int = 0
    vo2max_skipped: int = 0
