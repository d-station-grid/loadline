"""テストデータの factory。テストでは行を手で組み立てず、ここから作る。

- 保存先は conftest の session fixture が、テストごとのセッションに差し替える
- 親の id（user_id、workout_id）は作らない。どの利用者の行かはテストが渡す
- 既定の値は、新しく登録した利用者と、心拍のない Apple Watch の記録に揃える
- created_at と updated_at は DB の既定（now()）に任せる
"""

import secrets
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from itertools import count
from typing import Any, TypeVar

from polyfactory import Ignore, PostGenerated, Use
from polyfactory.factories.sqlalchemy_factory import (
    SQLAlchemyFactory,
    SQLAlchemyPersistenceMethod,
)

from app.models import IngestToken, Note, User, Vo2maxReading, Workout, WorkoutHeartRate

T = TypeVar("T")

_serial = count(1)


def _serial_time(start: datetime, step: timedelta) -> Use[Any, datetime]:
    """呼ぶたびに step ずつ進む日時。同じ利用者に何件作っても一意制約で落ちない。"""
    numbers = count()
    return Use(lambda: start + step * next(numbers))


def _serial_day(start: date) -> Use[Any, date]:
    """呼ぶたびに 1 日ずつ進む日付。"""
    numbers = count()
    return Use(lambda: start + timedelta(days=next(numbers)))


class BaseFactory(SQLAlchemyFactory[T]):
    __is_base_factory__ = True
    __set_primary_key__ = False
    __set_foreign_keys__ = False
    # commit はテストに任せる。flush で id が付けば足りる
    __persistence_method__ = SQLAlchemyPersistenceMethod.FLUSH


class UserFactory(BaseFactory[User]):
    __model__ = User

    # テストの偽のログインが決め打ちする uid-1 などと重ならない頭にする
    firebase_uid = Use(lambda: f"factory-uid-{next(_serial)}")
    email = PostGenerated(lambda _name, values: f"{values['firebase_uid']}@example.com")
    is_demo = False
    # 心拍の設定は、設定画面で入れるまで空
    max_heart_rate = None
    resting_heart_rate = None
    zone_boundary_1 = None
    zone_boundary_2 = None
    timezone = "Asia/Tokyo"
    review_weekday = 0
    send_notes_to_ai = True
    created_at = Ignore()
    updated_at = Ignore()


class IngestTokenFactory(BaseFactory[IngestToken]):
    """ハッシュだけのトークン。値で /ingest を呼ぶテストは issue_token で発行する。"""

    __model__ = IngestToken

    token_digest = Use(lambda: secrets.token_hex(32))
    last_four = PostGenerated(lambda _name, values: values["token_digest"][-4:])
    last_used_at = None
    revoked_at = None
    created_at = Ignore()


def _ended_at(_name: str, values: dict[str, Any]) -> datetime:
    started_at: datetime = values["started_at"]
    return started_at + timedelta(seconds=values["duration_sec"])


class WorkoutFactory(BaseFactory[Workout]):
    """心拍のない、Apple Watch のサイクリング 1 件。"""

    __model__ = Workout

    external_id = Use(lambda: f"workout-{next(_serial)}")
    sport = "ride"
    started_at = datetime(2026, 9, 13, 5, 0, tzinfo=UTC)
    duration_sec = 1800
    ended_at = PostGenerated(_ended_at)
    avg_heart_rate = None
    max_heart_rate = None
    created_at = Ignore()
    updated_at = Ignore()


class WorkoutHeartRateFactory(BaseFactory[WorkoutHeartRate]):
    """1 分ごとの心拍 1 件。"""

    __model__ = WorkoutHeartRate

    recorded_at = _serial_time(datetime(2026, 9, 13, 5, 0, tzinfo=UTC), timedelta(minutes=1))
    min_bpm = 115
    avg_bpm = 120
    max_bpm = 125


class Vo2maxReadingFactory(BaseFactory[Vo2maxReading]):
    __model__ = Vo2maxReading

    measured_at = _serial_time(datetime(2026, 9, 13, 8, 0, tzinfo=UTC), timedelta(days=1))
    value = Decimal("45.0")
    created_at = Ignore()


class NoteFactory(BaseFactory[Note]):
    """ラベルのないメモ 1 件。"""

    __model__ = Note

    # 1 日 1 件なので、呼ぶたびに 1 日ずつ進める
    date = _serial_day(date(2026, 9, 13))
    label = None
    body = "Legs felt heavy."
    created_at = Ignore()
    updated_at = Ignore()
