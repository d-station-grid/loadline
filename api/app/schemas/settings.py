from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.calendar import is_known_timezone
from app.domain.language import DEFAULT_LANGUAGE, Language


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
    language: Language = DEFAULT_LANGUAGE

    @field_validator("timezone")
    @classmethod
    def timezone_must_exist(cls, value: str) -> str:
        if not is_known_timezone(value):
            raise ValueError(f"unknown timezone: {value}")
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


def _drop_default(schema: dict[str, Any]) -> None:
    schema.pop("default", None)


class SettingsIn(SettingsFields):
    """PUT /settings の本文。心拍の 4 つは必須で、空（null）や省略は 422。

    負荷、強度ごとの時間、週次レビューの判定がすべてこの 4 つから出るので、そろわない設定は
    保存させない。境目は、web が最大心拍から初期値を入れる。読むとき（SettingsOut）は、
    必須にする前に作った利用者の空の値も返すので、SettingsFields のまま任意にしておく。

    言語は省略できる。省略したら保存済みの言語のまま。言語は PUT /settings/language でも
    変えられるので、ここで省略した人を英語に戻さないため。null は受け付けない。
    """

    max_heart_rate: int = Field(ge=100, le=250)
    resting_heart_rate: int = Field(ge=30, le=120)
    zone_boundary_1: int = Field(ge=60, le=250)  # Low と Mid の境目
    zone_boundary_2: int = Field(ge=60, le=250)  # Mid と High の境目
    # 省略したかは update_settings が model_fields_set で見分ける。初期値は使わないので、
    # 省略すると英語になると読めないよう、OpenAPI からは消す
    language: Language = Field(
        default=DEFAULT_LANGUAGE,
        json_schema_extra=_drop_default,
    )


class LanguageIn(BaseModel):
    """PUT /settings/language の本文。言語だけを書き換える。

    PUT /settings は心拍の 4 つが必須なので、心拍を入れる前の人は言語を変えられない。
    画面の言語は心拍と関係がないので、別の窓口で先に変えられるようにする。
    """

    language: Language


class SettingsOut(SettingsFields):
    """GET /settings の返事。トークンは末尾 4 文字だけ。未発行なら None。

    last_received_at は、Health Auto Export からの取り込みが最後に成功した日時。
    まだ一度も届いていなければ None。web の導入の案内が、送信アプリの設定が済んで
    最初の送信が届いたかを確かめるのに使う。記録が 0 件の送信でも、届けば日時は入る。
    """

    ingest_token_last_four: str | None = None
    last_received_at: datetime | None = None


class IngestTokenOut(BaseModel):
    """POST /settings/ingest-token の返事。平文のトークンはこのときだけ返す。"""

    token: str
    last_four: str
