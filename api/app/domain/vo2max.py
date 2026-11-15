"""VO2max の推移（実測と 30 日平均）と、週次レビューに渡す傾向。DB もタイムゾーンも持ち込まない。"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum

AVERAGE_DAYS = 30
# 差がこれ以上なら「上がった」「下がった」とする（ml/kg/min）。Apple Watch の推定は
# 1 回ごとにぶれるので、小さな差は「横ばい」に寄せる
TREND_MIN_CHANGE = 0.5


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


class Vo2maxTrend(StrEnum):
    """週次レビューに渡す VO2max の傾向。数値は渡さず区分だけにする。"""

    UP = "up"
    FLAT = "flat"
    DOWN = "down"


def vo2max_trend_of(change: float | None) -> Vo2maxTrend | None:
    """ダッシュボードのカードと同じ VO2max の差（最新の測定 − 28 日前かそれより前の最後の
    測定）を区分する。カードと週次レビューで向きが食い違わないよう、差は自分で計算しない。
    差がなければ None。"""
    if change is None:
        return None
    if change >= TREND_MIN_CHANGE:
        return Vo2maxTrend.UP
    if change <= -TREND_MIN_CHANGE:
        return Vo2maxTrend.DOWN
    return Vo2maxTrend.FLAT
