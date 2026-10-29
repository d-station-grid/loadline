from datetime import date

import pytest

from app.domain.period import EARLIEST_DAY, InvalidPeriodError, dashboard_period

TODAY = date(2026, 10, 29)


def test_defaults_to_first_workout_day_until_today() -> None:
    assert dashboard_period(TODAY, None, None, None, date(2026, 7, 1)) == (
        date(2026, 7, 1),
        TODAY,
    )


def test_without_any_workout_the_period_is_today_only() -> None:
    assert dashboard_period(TODAY, None, None, None, None) == (TODAY, TODAY)


def test_future_until_is_capped_at_today() -> None:
    assert dashboard_period(TODAY, date(2026, 10, 1), date(2026, 12, 31), None, None) == (
        date(2026, 10, 1),
        TODAY,
    )


def test_weeks_counts_back_from_until() -> None:
    assert dashboard_period(TODAY, None, date(2026, 10, 20), 2, None) == (
        date(2026, 10, 6),
        date(2026, 10, 20),
    )


def test_since_after_capped_until_is_rejected() -> None:
    """until を省いて未来の since を渡しても、今日で切った後に逆転を見つける。"""
    with pytest.raises(InvalidPeriodError) as e:
        dashboard_period(TODAY, date(2026, 11, 5), None, None, None)
    assert e.value.field == "since"


def test_since_before_earliest_day_is_rejected() -> None:
    with pytest.raises(InvalidPeriodError):
        dashboard_period(TODAY, date(1999, 12, 31), None, None, None)
    assert dashboard_period(TODAY, EARLIEST_DAY, None, None, None)[0] == EARLIEST_DAY
