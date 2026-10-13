from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SettingsFields(BaseModel):
    """users 表の設定の列。読むときも書くときも同じ項目。"""

    model_config = ConfigDict(from_attributes=True)

    max_heart_rate: int | None = Field(default=None, ge=100, le=250)
    resting_heart_rate: int | None = Field(default=None, ge=30, le=120)
    zone_boundary_1: int | None = Field(default=None, ge=60, le=250)  # Low と Mid の境目
    zone_boundary_2: int | None = Field(default=None, ge=60, le=250)  # Mid と High の境目
    timezone: str = "Asia/Tokyo"
    review_weekday: int = Field(default=0, ge=0, le=6)  # 0 が月曜、6 が日曜
    send_notes_to_ai: bool = True

    @field_validator("timezone")
    @classmethod
    def timezone_must_exist(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as e:
            raise ValueError(f"unknown timezone: {value}") from e
        return value

    @model_validator(mode="after")
    def boundaries_in_order(self) -> "SettingsFields":
        # 数値の前後関係はここで確かめる。あとの計算で前提にする
        if self.zone_boundary_1 is not None and self.zone_boundary_2 is not None:
            if not self.zone_boundary_1 < self.zone_boundary_2:
                raise ValueError("zone_boundary_1 must be lower than zone_boundary_2")
        if self.resting_heart_rate is not None and self.max_heart_rate is not None:
            if not self.resting_heart_rate < self.max_heart_rate:
                raise ValueError("resting_heart_rate must be lower than max_heart_rate")
        return self


class SettingsIn(SettingsFields):
    """PUT /settings の本文。"""


class SettingsOut(SettingsFields):
    """GET /settings の返事。トークンは末尾 4 文字だけ。未発行なら None。"""

    ingest_token_last_four: str | None = None


class IngestTokenOut(BaseModel):
    """POST /settings/ingest-token の返事。平文のトークンはこのときだけ返す。"""

    token: str
    last_four: str
