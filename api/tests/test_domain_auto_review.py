from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from app.domain.auto_review import is_auto_review_time

TOKYO = ZoneInfo("Asia/Tokyo")
MONDAY = 0


@pytest.mark.parametrize(
    ("local", "expected"),
    [
        # 2026-11-02 は月曜
        (datetime(2026, 11, 2, 5, 59, tzinfo=TOKYO), False),
        (datetime(2026, 11, 2, 6, 0, tzinfo=TOKYO), True),
        (datetime(2026, 11, 2, 23, 59, tzinfo=TOKYO), True),
        # 当日を逃したら作らない
        (datetime(2026, 11, 3, 6, 0, tzinfo=TOKYO), False),
        # 前の日の夜も作らない
        (datetime(2026, 11, 1, 23, 0, tzinfo=TOKYO), False),
    ],
)
def test_from_six_until_the_end_of_the_review_day(local: datetime, expected: bool) -> None:
    assert is_auto_review_time(local, "Asia/Tokyo", MONDAY) is expected


def test_judges_in_the_users_timezone_not_the_servers() -> None:
    # UTC では日曜の 21 時。東京では月曜の 6 時
    now = datetime(2026, 11, 1, 21, 0, tzinfo=UTC)

    assert is_auto_review_time(now, "Asia/Tokyo", MONDAY) is True
    assert is_auto_review_time(now, "UTC", MONDAY) is False


def test_follows_daylight_saving_time() -> None:
    # 2026-03-08（日）に米国は夏時間に入る。ニューヨークの 6 時は UTC の 10 時
    assert is_auto_review_time(datetime(2026, 3, 8, 10, 0, tzinfo=UTC), "America/New_York", 6)
    assert not is_auto_review_time(datetime(2026, 3, 8, 9, 59, tzinfo=UTC), "America/New_York", 6)


def test_naive_datetime_is_rejected() -> None:
    with pytest.raises(ValueError):
        is_auto_review_time(datetime(2026, 11, 2, 6, 0), "Asia/Tokyo", MONDAY)
