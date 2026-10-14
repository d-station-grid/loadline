"""VO2max の推移（実測と 30 日平均）。DB もタイムゾーンも持ち込まない。"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta

AVERAGE_DAYS = 30


@dataclass(frozen=True)
class Vo2maxPoint:
    """1 回の測定と、その日を含む直近 30 日の測定の平均。"""

    day: date
    value: float
    average: float


def vo2max_trend(readings: Sequence[tuple[date, float]]) -> list[Vo2maxPoint]:
    """測定ごとに、その日までの 30 日（その日を含む）の平均を添えて、日付の順に返す。

    日付は呼ぶ側が利用者のタイムゾーンで決めたもの。同じ日の測定は両方とも平均に入る。
    """
    ordered = sorted(readings, key=lambda r: r[0])
    points = []
    for day, value in ordered:
        since = day - timedelta(days=AVERAGE_DAYS - 1)
        window = [v for d, v in ordered if since <= d <= day]
        points.append(Vo2maxPoint(day=day, value=value, average=sum(window) / len(window)))
    return points
