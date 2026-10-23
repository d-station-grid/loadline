"""その週の状況の判定。アバターが何を話すかの土台。DB もタイムゾーンも持ち込まない。

数値と日付の比較はここで行い、LLM には任せない。疲労の境目は、余力（TSB）の一般的な
目安（−30 より下は負荷が高すぎ、+5 より上は疲労が抜けている）を、体力に対する割合に
当てはめたものにする。−30% より下を「疲労が溜まっている」、+5% より上を「休めている」とする。

割合は体力が小さいと大きく振れる。体力 20 前後では、疲労が少し上回っただけで −30% を割る。
そうなったときは、境目の割合を SituationThresholds で調整する。絶対値には切り替えない。
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum

from app.domain.load import FITNESS_DAYS, FitnessPoint

DAYS_IN_WEEK = 7


@dataclass(frozen=True)
class SituationThresholds:
    """判定の境目。値を変えるときは replace(DEFAULT_THRESHOLDS, ...) で作る。

    fatigued_below_ratio: 余力 ÷ 体力 がこれより下なら「疲労が溜まっている」
    fresh_above_ratio: これより上なら「休めている」
    enough_history_days: 最初のワークアウトからこの日数に満たないうちは、割合を使う判定を
        しない。体力は 42 日の平均で、それより短いと 0 から立ち上がる途中の値になる
    break_days: 記録のない日がこの日数以上続いた後の再開を「中断明け」とする
    max_unknown_load_days: その週に負荷の分からない日がこれを超えたら、割合を使う判定を
        しない。負荷の分からない日は 0 として計算されるので、疲労が低く出る
    """

    fatigued_below_ratio: float = -0.30
    fresh_above_ratio: float = 0.05
    enough_history_days: int = FITNESS_DAYS
    break_days: int = 14
    max_unknown_load_days: int = 0

    def __post_init__(self) -> None:
        if self.fatigued_below_ratio >= self.fresh_above_ratio:
            raise ValueError("fatigued_below_ratio must be less than fresh_above_ratio")
        if self.enough_history_days < 0:
            raise ValueError("enough_history_days must not be negative")
        if self.break_days < 1:
            raise ValueError("break_days must be at least 1")
        if not 0 <= self.max_unknown_load_days <= DAYS_IN_WEEK:
            raise ValueError(f"max_unknown_load_days must be between 0 and {DAYS_IN_WEEK}")


DEFAULT_THRESHOLDS = SituationThresholds()


class Situation(StrEnum):
    """その週の状況。"""

    NOT_ENOUGH_DATA = "not_enough_data"
    NO_TRAINING = "no_training"
    RETURNING = "returning"
    FATIGUED = "fatigued"
    FRESH = "fresh"
    STEADY = "steady"


@dataclass(frozen=True)
class PreviousWeek:
    """前の週の回数、時間、最終日の体力と疲労。前の週との差を出すために使う。"""

    workouts: int
    total_sec: int
    end: FitnessPoint


@dataclass(frozen=True)
class WeekInput:
    """判定する 1 週間（7 日）の材料。日付は呼ぶ側が利用者のタイムゾーンで決めたもの。

    workout_days: その週のワークアウト 1 件に 1 つの日付。同じ日に 2 件なら同じ日付を 2 回
    unknown_load_days: その週の 7 日のうち、負荷が分からない（心拍がない）ワークアウトを
        含む日の数。週の途中の欠けも数える。前の週の欠けも疲労にわずかに残るが、見ない
    end: 週の最終日の体力と疲労。週の途中の値は見ない。余力は体力 − 疲労で計算し直す
    previous: 前の週の材料。最初の週は None
    """

    start: date
    first_workout_day: date | None
    last_workout_day_before: date | None
    workout_days: Sequence[date]
    total_sec: int
    unknown_load_days: int
    end: FitnessPoint
    previous: PreviousWeek | None


@dataclass(frozen=True)
class WeekSituation:
    """判定の結果と、判定に使った数値。セリフに入れる数値と、確かめる数値をここで固定する。

    headroom_ratio は 余力 ÷ 体力。体力が 0 なら None。
    *_change は前の週との差。前の週の材料がなければ None。
    """

    situation: Situation
    start: date
    end: date
    fitness: float
    fatigue: float
    headroom: float
    headroom_ratio: float | None
    workouts: int
    total_sec: int
    unknown_load_days: int
    rest_days_before: int | None
    workouts_change: int | None
    total_sec_change: int | None
    fitness_change: float | None
    fatigue_change: float | None


def headroom_ratio(fitness: float, fatigue: float) -> float | None:
    """余力 ÷ 体力。体力が 0 なら割合は決まらないので None。"""
    return None if fitness == 0 else (fitness - fatigue) / fitness


def judge_week(
    week: WeekInput, thresholds: SituationThresholds = DEFAULT_THRESHOLDS
) -> WeekSituation:
    """その週の状況を決める。上から順に当てはめ、最初に当たったものにする。

    1. 記録が足りない: ワークアウトがまだ 1 件もない（その週より後に始めた場合も）
    2. 走れなかった週: その週のワークアウトが 0 件
    3. 中断明け: その週の最初のワークアウトの前に、記録のない日が break_days 以上続いた
    4. 記録が足りない: 割合を使う判定ができない。最初のワークアウトから週の最終日まで
       enough_history_days 未満、負荷の分からない日が max_unknown_load_days を超える、
       体力が 0 のどれか
    5. 疲労が溜まっている: 余力 ÷ 体力 が fatigued_below_ratio より下
    6. 休めている: 余力 ÷ 体力 が fresh_above_ratio より上
    7. 順調: どれにも当たらない

    2 と 3 は負荷を見ないので、記録の短さや心拍の欠けに関わらず判定する。
    """
    end = week.start + timedelta(days=DAYS_IN_WEEK - 1)
    _check(week, end)

    fitness = week.end.fitness
    fatigue = week.end.fatigue
    ratio = headroom_ratio(fitness, fatigue)
    workouts = len(week.workout_days)
    rest_days = _rest_days_before(week)
    started = week.first_workout_day is not None and week.first_workout_day <= end
    ratio_usable = (
        ratio is not None
        and week.first_workout_day is not None
        and (end - week.first_workout_day).days >= thresholds.enough_history_days
        and week.unknown_load_days <= thresholds.max_unknown_load_days
    )

    if not started:
        situation = Situation.NOT_ENOUGH_DATA
    elif workouts == 0:
        situation = Situation.NO_TRAINING
    elif rest_days is not None and rest_days >= thresholds.break_days:
        situation = Situation.RETURNING
    elif not ratio_usable or ratio is None:
        situation = Situation.NOT_ENOUGH_DATA
    elif ratio < thresholds.fatigued_below_ratio:
        situation = Situation.FATIGUED
    elif ratio > thresholds.fresh_above_ratio:
        situation = Situation.FRESH
    else:
        situation = Situation.STEADY

    prev = week.previous
    return WeekSituation(
        situation=situation,
        start=week.start,
        end=end,
        fitness=fitness,
        fatigue=fatigue,
        headroom=fitness - fatigue,
        headroom_ratio=ratio,
        workouts=workouts,
        total_sec=week.total_sec,
        unknown_load_days=week.unknown_load_days,
        rest_days_before=rest_days,
        workouts_change=None if prev is None else workouts - prev.workouts,
        total_sec_change=None if prev is None else week.total_sec - prev.total_sec,
        fitness_change=None if prev is None else fitness - prev.end.fitness,
        fatigue_change=None if prev is None else fatigue - prev.end.fatigue,
    )


def _check(week: WeekInput, end: date) -> None:
    """材料の日付と日数が週に合っているか。呼ぶ側の取り違えを早く落とす。"""
    if week.end.day != end:
        raise ValueError(f"end must be the last day of the week ({end}), got {week.end.day}")
    if any(not week.start <= d <= end for d in week.workout_days):
        raise ValueError("workout_days must be within the week")
    if week.last_workout_day_before is not None and week.last_workout_day_before >= week.start:
        raise ValueError("last_workout_day_before must be before the week")
    if not 0 <= week.unknown_load_days <= len(set(week.workout_days)):
        raise ValueError("unknown_load_days must be between 0 and the number of workout days")
    if week.previous is not None and week.previous.end.day != week.start - timedelta(days=1):
        raise ValueError("previous.end must be the day before the week")


def _rest_days_before(week: WeekInput) -> int | None:
    """その週の最初のワークアウトの前に、記録のない日が何日続いたか。

    前の日に記録があれば 0。その週にワークアウトがないか、それより前の記録がなければ None。
    """
    if not week.workout_days or week.last_workout_day_before is None:
        return None
    return (min(week.workout_days) - week.last_workout_day_before).days - 1
