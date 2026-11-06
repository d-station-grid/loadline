from datetime import date, timedelta

import pytest

from app.domain.load import FitnessPoint, WorkoutLoad, ZoneTimes
from app.domain.summary import (
    CHANGE_DAYS,
    VO2MAX_CHANGE_DAYS,
    WorkoutItem,
    fitness_change,
    previous_period,
    totals,
    vo2max_baseline_before,
    weekly_zones,
)

UNTIL = date(2026, 10, 25)
# 1 時間のうち low 40 分、mid 15 分、high 5 分
ZONES = ZoneTimes(low=2400, mid=900, high=300)


def point(day: date, fitness: float, fatigue: float) -> FitnessPoint:
    return FitnessPoint(
        day=day, load=0.0, fitness=fitness, fatigue=fatigue, headroom=fitness - fatigue
    )


def item(
    day: date,
    duration_sec: int = 3600,
    load: float | None = 50.0,
    zones: ZoneTimes | None = ZONES,
) -> WorkoutItem:
    return WorkoutItem(day=day, duration_sec=duration_sec, load=WorkoutLoad(load=load, zones=zones))


def test_fitness_change_compares_with_seven_days_before() -> None:
    week_ago = UNTIL - timedelta(days=CHANGE_DAYS)
    # 前日の値ではなく、7 日前の値と比べる
    points = [
        point(week_ago, 60.0, 50.0),
        point(UNTIL - timedelta(days=1), 99.0, 99.0),
        point(UNTIL, 65.0, 72.0),
    ]

    change = fitness_change(points, UNTIL)

    assert change is not None
    assert change.fitness == pytest.approx(5.0)
    assert change.fatigue == pytest.approx(22.0)
    # 余力は 10 から −7 へ
    assert change.headroom == pytest.approx(-17.0)


def test_fitness_change_is_none_without_the_day_to_compare() -> None:
    assert fitness_change([point(UNTIL, 65.0, 72.0)], UNTIL) is None
    assert fitness_change([point(UNTIL - timedelta(days=CHANGE_DAYS), 1, 1)], UNTIL) is None


def test_vo2max_baseline_is_28_days_before() -> None:
    assert VO2MAX_CHANGE_DAYS == 28
    assert vo2max_baseline_before(UNTIL) == date(2026, 9, 27)


def test_weekly_zones_count_back_from_until_in_seven_days() -> None:
    since = UNTIL - timedelta(days=13)
    items = [
        item(since),  # 古い週の初日
        item(UNTIL - timedelta(days=7)),  # 古い週の最終日
        item(UNTIL - timedelta(days=6)),  # 新しい週の初日
        item(UNTIL),
        item(UNTIL),
        item(since - timedelta(days=1)),  # 期間の外
    ]

    weeks = weekly_zones(items, since, UNTIL)

    assert [(w.start, w.end) for w in weeks] == [
        (since, UNTIL - timedelta(days=7)),
        (UNTIL - timedelta(days=6), UNTIL),
    ]
    assert weeks[0].zones == ZoneTimes(low=4800, mid=1800, high=600)
    assert weeks[1].zones == ZoneTimes(low=7200, mid=2700, high=900)


def test_weekly_zones_skip_workouts_without_heart_rate_and_count_them() -> None:
    items = [item(UNTIL), item(UNTIL, zones=None)]

    (week,) = weekly_zones(items, UNTIL - timedelta(days=6), UNTIL)

    assert week.zones == ZONES
    assert week.workouts_without_zones == 1


def test_weekly_zones_keep_empty_weeks_and_a_short_oldest_week() -> None:
    """7 の倍数でない期間は、いちばん古い区切りだけ短い。記録のない週も 0 秒で返す。"""
    since = UNTIL - timedelta(days=8)

    weeks = weekly_zones([], since, UNTIL)

    assert [(w.start, w.end) for w in weeks] == [
        (since, since + timedelta(days=1)),
        (UNTIL - timedelta(days=6), UNTIL),
    ]
    assert all(w.zones == ZoneTimes(0, 0, 0) for w in weeks)
    assert all(w.workouts_without_zones == 0 for w in weeks)


def test_previous_period_has_the_same_length() -> None:
    since = UNTIL - timedelta(days=27)

    assert previous_period(since, UNTIL) == (
        since - timedelta(days=28),
        since - timedelta(days=1),
    )


def test_totals_sum_inside_the_period() -> None:
    items = [
        item(UNTIL - timedelta(days=6), duration_sec=1800, load=30.0),
        item(UNTIL, duration_sec=3600, load=90.0),
        item(UNTIL - timedelta(days=7), duration_sec=9999, load=999.0),  # 期間の外
    ]

    result = totals(items, UNTIL - timedelta(days=6), UNTIL)

    assert result.workouts == 2
    assert result.total_sec == 5400
    assert result.load == pytest.approx(120.0)
    assert result.load_per_workout == pytest.approx(60.0)
    assert result.workouts_without_load == 0


def test_totals_leave_out_unknown_load_but_count_it() -> None:
    items = [item(UNTIL, load=90.0), item(UNTIL, load=None, zones=None)]

    result = totals(items, UNTIL, UNTIL)

    assert result.workouts == 2
    assert result.total_sec == 7200
    assert result.load == pytest.approx(90.0)
    # 負荷の分かる 1 回で割る。2 回で割ると 1 回あたりが低く出る
    assert result.load_per_workout == pytest.approx(90.0)
    assert result.workouts_without_load == 1


def test_totals_without_workouts_is_zero_and_without_any_load_is_none() -> None:
    empty = totals([], UNTIL, UNTIL)
    assert (empty.workouts, empty.total_sec, empty.load, empty.load_per_workout) == (
        0,
        0,
        0,
        None,
    )

    unknown = totals([item(UNTIL, load=None)], UNTIL, UNTIL)
    assert unknown.load is None
    assert unknown.load_per_workout is None
    assert unknown.workouts_without_load == 1
