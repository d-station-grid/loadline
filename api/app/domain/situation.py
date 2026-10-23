"""その週の状況の判定。アバターが何を話すかの土台。DB もタイムゾーンも持ち込まない。

数値と日付の比較はここで行い、LLM には任せない。境目は Intervals.icu の既定に合わせる。
Intervals.icu は Form（余力）を体力に対する割合で見て、−30% より下を High Risk、
+5% より上を Fresh（+20% より上は Transition）としている。独自の境目は作らない。
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum

from app.domain.load import FITNESS_DAYS, FitnessPoint

# 最初のワークアウトからこの日数たつまでは「記録が足りない」。体力は 42 日の平均で、
# それより短いと 0 から立ち上がる途中の値になり、割合が大きく振れる
ENOUGH_HISTORY_DAYS = FITNESS_DAYS

# 何も記録しない日がこの日数以上続いた後の再開を「中断明け」とする
BREAK_DAYS = 14

# 余力 ÷ 体力 の境目（Intervals.icu の High Risk と Fresh）
FATIGUED_BELOW = -0.30
FRESH_ABOVE = 0.05


class Situation(StrEnum):
    """その週の状況。上から順に当てはめ、最初に当たったものにする。"""

    NOT_ENOUGH_DATA = "not_enough_data"
    NO_TRAINING = "no_training"
    RETURNING = "returning"
    FATIGUED = "fatigued"
    FRESH = "fresh"
    STEADY = "steady"


@dataclass(frozen=True)
class WeekInput:
    """判定する 1 週間（7 日）の材料。日付は呼ぶ側が利用者のタイムゾーンで決めたもの。

    end は週の最終日の体力と疲労。週の途中の値は見ない。
    """

    start: date
    first_workout_day: date | None
    last_workout_day_before: date | None
    workout_days: Sequence[date]
    total_sec: int
    previous_workouts: int | None
    previous_total_sec: int | None
    end: FitnessPoint


@dataclass(frozen=True)
class WeekSituation:
    """判定の結果と、判定に使った数値。セリフに入れる数値と、確かめる数値をここで固定する。

    form_ratio は 余力 ÷ 体力。体力が 0 なら None。
    前の週との差は、前の週の材料がなければ None。
    """

    situation: Situation
    start: date
    end: date
    fitness: float
    fatigue: float
    headroom: float
    form_ratio: float | None
    workouts: int
    total_sec: int
    workouts_change: int | None
    total_sec_change: int | None
    rest_days_before: int | None


def form_ratio(fitness: float, headroom: float) -> float | None:
    """余力 ÷ 体力。体力が 0 なら割合は決まらないので None。"""
    return None if fitness == 0 else headroom / fitness


def judge_week(week: WeekInput) -> WeekSituation:
    """その週の状況を決める。

    1. 記録が足りない: ワークアウトがまだないか、最初のワークアウトから週の最終日まで 42 日未満
    2. 走れなかった週: その週のワークアウトが 0 件
    3. 中断明け: その週の最初のワークアウトの前に、記録のない日が 14 日以上続いた
    4. 疲労が溜まっている: 余力 ÷ 体力 が −30% より下
    5. 休めている: 余力 ÷ 体力 が +5% より上
    6. 順調: どれにも当たらない（体力が 0 で割合が決まらないときも含む）
    """
    end = week.start + timedelta(days=6)
    if week.end.day != end:
        raise ValueError(f"end must be the last day of the week ({end}), got {week.end.day}")
    if any(not week.start <= d <= end for d in week.workout_days):
        raise ValueError("workout_days must be within the week")
    if week.last_workout_day_before is not None and week.last_workout_day_before >= week.start:
        raise ValueError("last_workout_day_before must be before the week")

    ratio = form_ratio(week.end.fitness, week.end.headroom)
    workouts = len(week.workout_days)
    rest_days = _rest_days_before(week)

    if week.first_workout_day is None or (end - week.first_workout_day).days < ENOUGH_HISTORY_DAYS:
        situation = Situation.NOT_ENOUGH_DATA
    elif workouts == 0:
        situation = Situation.NO_TRAINING
    elif rest_days is not None and rest_days >= BREAK_DAYS:
        situation = Situation.RETURNING
    elif ratio is not None and ratio < FATIGUED_BELOW:
        situation = Situation.FATIGUED
    elif ratio is not None and ratio > FRESH_ABOVE:
        situation = Situation.FRESH
    else:
        situation = Situation.STEADY

    return WeekSituation(
        situation=situation,
        start=week.start,
        end=end,
        fitness=week.end.fitness,
        fatigue=week.end.fatigue,
        headroom=week.end.headroom,
        form_ratio=ratio,
        workouts=workouts,
        total_sec=week.total_sec,
        workouts_change=None
        if week.previous_workouts is None
        else workouts - week.previous_workouts,
        total_sec_change=None
        if week.previous_total_sec is None
        else week.total_sec - week.previous_total_sec,
        rest_days_before=rest_days,
    )


def _rest_days_before(week: WeekInput) -> int | None:
    """その週の最初のワークアウトの前に、記録のない日が何日続いたか。

    前の日に記録があれば 0。その週にワークアウトがないか、それより前の記録がなければ None。
    """
    if not week.workout_days or week.last_workout_day_before is None:
        return None
    return (min(week.workout_days) - week.last_workout_day_before).days - 1
