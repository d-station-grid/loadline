"""ダッシュボードの数字の比較と合計。前週との差、週ごとの強度の時間、期間の合計。

DB もタイムゾーンも持ち込まない。日付は呼ぶ側が利用者のタイムゾーンで決めたもの。
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from app.domain.load import FitnessPoint, WorkoutLoad, ZoneTimes

# カードの「vs last week」。今日の値と 7 日前の値を比べる
CHANGE_DAYS = 7
# VO2max の「in 4 weeks」。測定は毎日ではないので、28 日前かそれより前の最後の測定と比べる
VO2MAX_CHANGE_DAYS = 28


@dataclass(frozen=True)
class FitnessChange:
    """until の値 − その CHANGE_DAYS 日前の値。"""

    fitness: float
    fatigue: float
    headroom: float


@dataclass(frozen=True)
class WorkoutItem:
    """合計に使う 1 回ぶん。day は利用者のタイムゾーンでの日付。"""

    day: date
    duration_sec: int
    load: WorkoutLoad


@dataclass(frozen=True)
class WeekZones:
    """7 日ぶん（start から end まで、両端を含む）の強度ごとの時間。

    zones は心拍の分かる回だけを足す。workouts_without_zones は足せなかった回の数。
    """

    start: date
    end: date
    zones: ZoneTimes
    workouts_without_zones: int


@dataclass(frozen=True)
class Totals:
    """期間（start から end まで、両端を含む）の合計。

    load は負荷の分かる回だけを足す。回はあるのに 1 回も分からなければ None（0 と区別するため）。
    load_per_workout は 負荷の合計 ÷ 負荷の分かる回の数。
    """

    start: date
    end: date
    workouts: int
    total_sec: int
    load: float | None
    load_per_workout: float | None
    workouts_without_load: int


def fitness_change(points: Sequence[FitnessPoint], until: date) -> FitnessChange | None:
    """until とその CHANGE_DAYS 日前の体力・疲労・余力の差。どちらかの日がなければ None。"""
    by_day = {p.day: p for p in points}
    now = by_day.get(until)
    before = by_day.get(until - timedelta(days=CHANGE_DAYS))
    if now is None or before is None:
        return None
    return FitnessChange(
        fitness=now.fitness - before.fitness,
        fatigue=now.fatigue - before.fatigue,
        headroom=now.headroom - before.headroom,
    )


def vo2max_baseline_before(latest_day: date) -> date:
    """VO2max の差の比べる相手は、この日かそれより前の最後の測定。"""
    return latest_day - timedelta(days=VO2MAX_CHANGE_DAYS)


def weekly_zones(items: Sequence[WorkoutItem], since: date, until: date) -> list[WeekZones]:
    """until から 7 日ずつさかのぼって区切った、週ごとの強度の時間。古い順に返す。

    期間が 7 の倍数の日数でなければ、いちばん古い区切りだけ 7 日より短い（start が since）。
    期間の外の回は捨てる。
    """
    weeks: list[WeekZones] = []
    end = until
    while end >= since:
        start = max(end - timedelta(days=6), since)
        inside = [i.load.zones for i in items if start <= i.day <= end]
        known = [z for z in inside if z is not None]
        weeks.append(
            WeekZones(
                start=start,
                end=end,
                zones=ZoneTimes(
                    low=sum(z.low for z in known),
                    mid=sum(z.mid for z in known),
                    high=sum(z.high for z in known),
                ),
                workouts_without_zones=len(inside) - len(known),
            )
        )
        end = start - timedelta(days=1)
    return weeks[::-1]


def previous_period(since: date, until: date) -> tuple[date, date]:
    """since の前の、同じ日数の期間（両端を含む）。"""
    days = (until - since).days + 1
    return since - timedelta(days=days), since - timedelta(days=1)


def totals(items: Sequence[WorkoutItem], start: date, end: date) -> Totals:
    """start から end まで（両端を含む）の回数、時間、負荷の合計。期間の外の回は捨てる。"""
    inside = [i for i in items if start <= i.day <= end]
    loads = [i.load.load for i in inside if i.load.load is not None]
    # 回がなければ 0。回があって 1 回も負荷が分からなければ None
    load = sum(loads) if loads or not inside else None
    return Totals(
        start=start,
        end=end,
        workouts=len(inside),
        total_sec=sum(i.duration_sec for i in inside),
        load=load,
        load_per_workout=sum(loads) / len(loads) if loads else None,
        workouts_without_load=len(inside) - len(loads),
    )
