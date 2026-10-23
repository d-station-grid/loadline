from datetime import date, timedelta

import pytest

from app.domain.load import FitnessPoint
from app.domain.situation import (
    BREAK_DAYS,
    ENOUGH_HISTORY_DAYS,
    Situation,
    WeekInput,
    judge_week,
)

# 2026-09-28（月）からの 1 週間
MONDAY = date(2026, 9, 28)
SUNDAY = MONDAY + timedelta(days=6)
LONG_AGO = date(2026, 6, 29)


def week(
    *,
    fitness: float = 20.0,
    fatigue: float = 22.0,
    workout_days: tuple[date, ...] = (MONDAY,),
    total_sec: int = 3600,
    first_workout_day: date | None = LONG_AGO,
    last_workout_day_before: date | None = MONDAY - timedelta(days=1),
    previous_workouts: int | None = 3,
    previous_total_sec: int | None = 7200,
) -> WeekInput:
    return WeekInput(
        start=MONDAY,
        first_workout_day=first_workout_day,
        last_workout_day_before=last_workout_day_before,
        workout_days=workout_days,
        total_sec=total_sec,
        previous_workouts=previous_workouts,
        previous_total_sec=previous_total_sec,
        end=FitnessPoint(
            day=SUNDAY, load=0.0, fitness=fitness, fatigue=fatigue, headroom=fitness - fatigue
        ),
    )


def test_real_week_with_much_more_training_is_fatigued() -> None:
    # 手元の実データの 9/28 の週: 11 回、357 分、体力 18.9、疲労 48.8（余力 −158%）
    days = (MONDAY,) * 11
    result = judge_week(
        week(
            fitness=18.9,
            fatigue=48.8,
            workout_days=days,
            total_sec=357 * 60,
            previous_workouts=7,
            previous_total_sec=201 * 60,
        )
    )

    assert result.situation == Situation.FATIGUED
    assert result.form_ratio == pytest.approx(-29.9 / 18.9)
    assert result.workouts == 11
    assert result.workouts_change == 4
    assert result.total_sec_change == 156 * 60
    assert (result.start, result.end) == (MONDAY, SUNDAY)


def test_no_workouts_yet_is_not_enough_data() -> None:
    result = judge_week(
        week(workout_days=(), total_sec=0, first_workout_day=None, last_workout_day_before=None)
    )

    assert result.situation == Situation.NOT_ENOUGH_DATA


def test_history_shorter_than_fitness_days_is_not_enough_data() -> None:
    # 最初の日から週の最終日まで 41 日ならまだ足りず、42 日で判定する
    short = judge_week(week(first_workout_day=SUNDAY - timedelta(days=ENOUGH_HISTORY_DAYS - 1)))
    enough = judge_week(week(first_workout_day=SUNDAY - timedelta(days=ENOUGH_HISTORY_DAYS)))

    assert short.situation == Situation.NOT_ENOUGH_DATA
    assert enough.situation == Situation.STEADY


def test_week_without_workouts_is_no_training() -> None:
    # 余力が高くても、走っていない週は「休めている」ではなく「走れなかった週」
    result = judge_week(week(fitness=20.0, fatigue=5.0, workout_days=(), total_sec=0))

    assert result.situation == Situation.NO_TRAINING
    assert result.rest_days_before is None


def test_restart_after_long_break_is_returning() -> None:
    # 9/13 の後、9/14〜9/27 の 14 日休んで 9/28 に再開。13 日の休みなら中断ではない
    returning = judge_week(week(last_workout_day_before=MONDAY - timedelta(days=BREAK_DAYS + 1)))
    not_yet = judge_week(week(last_workout_day_before=MONDAY - timedelta(days=BREAK_DAYS)))

    assert returning.situation == Situation.RETURNING
    assert returning.rest_days_before == BREAK_DAYS
    assert not_yet.situation == Situation.STEADY
    assert not_yet.rest_days_before == BREAK_DAYS - 1


def test_rest_days_are_counted_to_first_workout_of_the_week() -> None:
    # 週の途中（水曜）に再開しても、週の頭からの休みも数える
    # 9/15 の後、9/16〜9/29 の 14 日休んで 9/30 に再開
    result = judge_week(
        week(
            workout_days=(MONDAY + timedelta(days=5), MONDAY + timedelta(days=2)),
            last_workout_day_before=MONDAY - timedelta(days=BREAK_DAYS - 1),
        )
    )

    assert result.rest_days_before == BREAK_DAYS
    assert result.situation == Situation.RETURNING


def test_returning_wins_over_fatigued() -> None:
    result = judge_week(
        week(fitness=10.0, fatigue=30.0, last_workout_day_before=MONDAY - timedelta(days=30))
    )

    assert result.situation == Situation.RETURNING


@pytest.mark.parametrize(
    ("fatigue", "expected"),
    [
        (26.02, Situation.FATIGUED),  # 余力 −6.02 ÷ 体力 20 = −30.1%
        (26.0, Situation.STEADY),  # ちょうど −30% は高リスクに入れない
        (20.0, Situation.STEADY),
        (19.0, Situation.STEADY),  # ちょうど +5% は休めているに入れない
        (18.98, Situation.FRESH),  # +5.1%
    ],
)
def test_form_ratio_boundaries(fatigue: float, expected: Situation) -> None:
    assert judge_week(week(fitness=20.0, fatigue=fatigue)).situation == expected


def test_zero_fitness_has_no_ratio_and_is_steady() -> None:
    # 心拍のないワークアウトばかりで負荷が 0 のとき
    result = judge_week(week(fitness=0.0, fatigue=0.0))

    assert result.form_ratio is None
    assert result.situation == Situation.STEADY


def test_first_week_has_no_change_from_previous() -> None:
    result = judge_week(week(previous_workouts=None, previous_total_sec=None))

    assert result.workouts_change is None
    assert result.total_sec_change is None


def test_end_must_be_last_day_of_the_week() -> None:
    bad = week()
    bad = WeekInput(**{**bad.__dict__, "end": FitnessPoint(MONDAY, 0.0, 20.0, 20.0, 0.0)})

    with pytest.raises(ValueError, match="last day of the week"):
        judge_week(bad)


def test_workout_days_must_be_within_the_week() -> None:
    with pytest.raises(ValueError, match="within the week"):
        judge_week(week(workout_days=(SUNDAY + timedelta(days=1),)))


def test_previous_workout_must_be_before_the_week() -> None:
    with pytest.raises(ValueError, match="before the week"):
        judge_week(week(last_workout_day_before=MONDAY))
