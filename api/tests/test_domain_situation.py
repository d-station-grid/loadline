from dataclasses import replace
from datetime import date, timedelta

import pytest

from app.domain.load import DailyLoad, FitnessPoint, fitness_fatigue
from app.domain.situation import (
    DEFAULT_THRESHOLDS,
    PreviousWeek,
    Situation,
    SituationThresholds,
    WeekInput,
    headroom_ratio,
    judge_week,
)

# 2026-09-28（月）からの 1 週間
MONDAY = date(2026, 9, 28)
SUNDAY = MONDAY + timedelta(days=6)
LONG_AGO = date(2026, 6, 29)
ENOUGH_HISTORY_DAYS = DEFAULT_THRESHOLDS.enough_history_days
BREAK_DAYS = DEFAULT_THRESHOLDS.break_days


def point(day: date, fitness: float, fatigue: float) -> FitnessPoint:
    return FitnessPoint(
        day=day, load=0.0, fitness=fitness, fatigue=fatigue, headroom=fitness - fatigue
    )


def previous(
    workouts: int = 3, total_sec: int = 7200, fitness: float = 19.0, fatigue: float = 25.0
) -> PreviousWeek:
    return PreviousWeek(
        workouts=workouts,
        total_sec=total_sec,
        end=point(MONDAY - timedelta(days=1), fitness, fatigue),
    )


def week(
    *,
    fitness: float = 20.0,
    fatigue: float = 22.0,
    workout_days: tuple[date, ...] = (MONDAY,),
    total_sec: int = 3600,
    unknown_load_days: int = 0,
    first_workout_day: date | None = LONG_AGO,
    last_workout_day_before: date | None = MONDAY - timedelta(days=1),
    prev: PreviousWeek | None = None,
) -> WeekInput:
    return WeekInput(
        start=MONDAY,
        first_workout_day=first_workout_day,
        last_workout_day_before=last_workout_day_before,
        workout_days=workout_days,
        total_sec=total_sec,
        unknown_load_days=unknown_load_days,
        end=point(SUNDAY, fitness, fatigue),
        previous=prev,
    )


def test_real_week_with_much_more_training_is_fatigued() -> None:
    # 手元の実データの 9/28 の週: 11 回、357 分、体力 18.9、疲労 48.8（余力 −158%）
    # 前の週（9/21）は 7 回、201 分、体力 14.1、疲労 29.1
    result = judge_week(
        week(
            fitness=18.9,
            fatigue=48.8,
            workout_days=(MONDAY,) * 11,
            total_sec=357 * 60,
            prev=previous(workouts=7, total_sec=201 * 60, fitness=14.1, fatigue=29.1),
        )
    )

    assert result.situation == Situation.FATIGUED
    assert result.headroom == pytest.approx(-29.9)
    assert result.headroom_ratio == pytest.approx(-29.9 / 18.9)
    assert result.workouts == 11
    assert result.workouts_change == 4
    assert result.total_sec_change == 156 * 60
    assert result.fitness_change == pytest.approx(4.8)
    assert result.fatigue_change == pytest.approx(19.7)
    assert (result.start, result.end) == (MONDAY, SUNDAY)


def test_headroom_is_recalculated_from_fitness_and_fatigue() -> None:
    # 受け取った余力が体力 − 疲労と合わなくても、判定は体力と疲労から計算し直す
    given = week(fitness=20.0, fatigue=30.0)
    given = replace(given, end=replace(given.end, headroom=5.0))

    result = judge_week(given)

    assert result.headroom == -10.0
    assert result.situation == Situation.FATIGUED


def test_no_workouts_yet_is_not_enough_data() -> None:
    result = judge_week(
        week(workout_days=(), total_sec=0, first_workout_day=None, last_workout_day_before=None)
    )

    assert result.situation == Situation.NOT_ENOUGH_DATA


def test_week_before_the_first_workout_is_not_enough_data() -> None:
    # 始める前の週は「走れなかった週」ではない
    result = judge_week(
        week(
            workout_days=(),
            total_sec=0,
            first_workout_day=SUNDAY + timedelta(days=1),
            last_workout_day_before=None,
        )
    )

    assert result.situation == Situation.NOT_ENOUGH_DATA


def test_short_history_stops_only_ratio_based_judgement() -> None:
    # 最初の日から週の最終日まで 41 日ならまだ足りず、42 日で割合を使って判定する
    short = judge_week(week(first_workout_day=SUNDAY - timedelta(days=ENOUGH_HISTORY_DAYS - 1)))
    enough = judge_week(week(first_workout_day=SUNDAY - timedelta(days=ENOUGH_HISTORY_DAYS)))

    assert short.situation == Situation.NOT_ENOUGH_DATA
    assert enough.situation == Situation.STEADY


def test_short_history_still_judges_no_training_and_returning() -> None:
    first = MONDAY - timedelta(days=20)
    no_training = judge_week(
        week(workout_days=(), total_sec=0, first_workout_day=first, last_workout_day_before=first)
    )
    returning = judge_week(
        week(first_workout_day=first, last_workout_day_before=first, workout_days=(SUNDAY,))
    )

    assert no_training.situation == Situation.NO_TRAINING
    assert returning.situation == Situation.RETURNING


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
def test_headroom_ratio_boundaries(fatigue: float, expected: Situation) -> None:
    assert judge_week(week(fitness=20.0, fatigue=fatigue)).situation == expected


def test_zero_fitness_has_no_ratio_and_is_not_enough_data() -> None:
    result = judge_week(week(fitness=0.0, fatigue=0.0))

    assert headroom_ratio(0.0, 0.0) is None
    assert result.headroom_ratio is None
    assert result.situation == Situation.NOT_ENOUGH_DATA


def test_week_without_heart_rate_is_not_judged_as_fresh() -> None:
    # 体力・疲労が 20 の状態から毎日 1 時間運動した週。心拍がないと負荷は 0 として計算され、
    # 疲労が下がって「休めている」に見えてしまう
    days = tuple(MONDAY + timedelta(days=i) for i in range(7))
    end = fitness_fatigue([DailyLoad(d, None) for d in days], 20.0, 20.0)[-1]
    without_hr = WeekInput(
        start=MONDAY,
        first_workout_day=LONG_AGO,
        last_workout_day_before=MONDAY - timedelta(days=1),
        workout_days=days,
        total_sec=7 * 3600,
        unknown_load_days=7,
        end=end,
        previous=None,
    )

    ignoring_gaps = replace(DEFAULT_THRESHOLDS, max_unknown_load_days=7)
    assert judge_week(without_hr, ignoring_gaps).situation == Situation.FRESH
    assert judge_week(without_hr).situation == Situation.NOT_ENOUGH_DATA


def test_one_unknown_day_mid_week_stops_ratio_based_judgement() -> None:
    days = (MONDAY, MONDAY + timedelta(days=3))
    result = judge_week(week(fitness=20.0, fatigue=40.0, workout_days=days, unknown_load_days=1))

    assert result.situation == Situation.NOT_ENOUGH_DATA
    assert result.unknown_load_days == 1


def test_unknown_load_does_not_stop_returning() -> None:
    result = judge_week(
        week(unknown_load_days=1, last_workout_day_before=MONDAY - timedelta(days=30))
    )

    assert result.situation == Situation.RETURNING


def test_thresholds_can_be_tuned() -> None:
    # 余力 −40% は既定では疲労、境目を −50% にすると順調
    tuned = replace(DEFAULT_THRESHOLDS, fatigued_below_ratio=-0.5)

    assert judge_week(week(fitness=20.0, fatigue=28.0)).situation == Situation.FATIGUED
    assert judge_week(week(fitness=20.0, fatigue=28.0), tuned).situation == Situation.STEADY


def test_break_days_can_be_tuned() -> None:
    # 10 日休んで再開。既定の 14 日では順調、10 日にすると中断明け
    given = week(last_workout_day_before=MONDAY - timedelta(days=11))

    assert judge_week(given).situation == Situation.STEADY
    assert (
        judge_week(given, replace(DEFAULT_THRESHOLDS, break_days=10)).situation
        == Situation.RETURNING
    )


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"fatigued_below_ratio": 0.1}, "less than fresh_above_ratio"),
        ({"enough_history_days": -1}, "must not be negative"),
        ({"break_days": 0}, "at least 1"),
        ({"max_unknown_load_days": 8}, "between 0 and 7"),
    ],
)
def test_invalid_thresholds_are_rejected(changes: dict[str, float], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        SituationThresholds(**changes)  # type: ignore[arg-type]


def test_first_week_has_no_change_from_previous() -> None:
    result = judge_week(week(prev=None))

    assert result.workouts_change is None
    assert result.total_sec_change is None
    assert result.fitness_change is None
    assert result.fatigue_change is None


def test_end_must_be_last_day_of_the_week() -> None:
    with pytest.raises(ValueError, match="last day of the week"):
        judge_week(replace(week(), end=point(MONDAY, 20.0, 20.0)))


def test_workout_days_must_be_within_the_week() -> None:
    with pytest.raises(ValueError, match="within the week"):
        judge_week(week(workout_days=(SUNDAY + timedelta(days=1),)))


def test_previous_workout_must_be_before_the_week() -> None:
    with pytest.raises(ValueError, match="before the week"):
        judge_week(week(last_workout_day_before=MONDAY))


def test_unknown_load_days_must_not_exceed_workout_days() -> None:
    # 同じ日に 2 件あっても、欠けた日は 1 日
    with pytest.raises(ValueError, match="number of workout days"):
        judge_week(week(workout_days=(MONDAY, MONDAY), unknown_load_days=2))


def test_previous_end_must_be_the_day_before_the_week() -> None:
    prev = replace(previous(), end=point(MONDAY - timedelta(days=2), 19.0, 25.0))

    with pytest.raises(ValueError, match="day before the week"):
        judge_week(week(prev=prev))
