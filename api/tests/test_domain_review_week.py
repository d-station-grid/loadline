from datetime import date, timedelta

import pytest

from app.domain.review_week import review_period

# 2026-10-19 は月曜、2026-10-25 は日曜
MONDAY = date(2026, 10, 19)


def test_monday_review_on_saturday_looks_back_at_the_week_before() -> None:
    """曜日が月曜で今日が 10/24（土）なら、10/19（月）の回で 10/12〜10/18。"""
    assert review_period(date(2026, 10, 24), 0) == (date(2026, 10, 12), date(2026, 10, 18))


def test_on_the_review_day_the_period_ends_yesterday() -> None:
    assert review_period(MONDAY, 0) == (date(2026, 10, 12), date(2026, 10, 18))


def test_the_day_before_the_review_day_still_uses_the_previous_review() -> None:
    """日曜の振り返りで今日が土曜なら、まだ先週の日曜の回。"""
    assert review_period(date(2026, 10, 24), 6) == (date(2026, 10, 11), date(2026, 10, 17))


@pytest.mark.parametrize("weekday", range(7))
@pytest.mark.parametrize("offset", range(7))
def test_period_is_seven_days_ending_the_day_before_a_review_day(weekday: int, offset: int) -> None:
    today = MONDAY + timedelta(days=offset)

    start, end = review_period(today, weekday)

    assert end - start == timedelta(days=6)
    assert (end + timedelta(days=1)).weekday() == weekday
    assert end < today <= end + timedelta(days=7)


@pytest.mark.parametrize("weekday", [-1, 7])
def test_weekday_out_of_range_is_rejected(weekday: int) -> None:
    with pytest.raises(ValueError, match="review_weekday"):
        review_period(MONDAY, weekday)
