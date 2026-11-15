"""VO2max の推移（実測と 30 日平均）と、週次レビューに渡す傾向。DB もタイムゾーンも持ち込まない。"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum

AVERAGE_DAYS = 30
# 傾向は、週の最終日までの最新の平均と、その 28 日前かそれより前の最後の平均を比べる。
# ダッシュボードの「4 週前との差」と同じ間隔
TREND_DAYS = 28
# 30 日平均の差がこれ以上なら「上がった」「下がった」とする（ml/kg/min）。
# Apple Watch の推定は 1 回ごとにぶれるので、平均どうしを比べ、小さな差は「横ばい」に寄せる
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


def vo2max_trend_until(points: Sequence[Vo2maxPoint], end: date) -> Vo2maxTrend | None:
    """end までの最新の 30 日平均と、その TREND_DAYS 日前かそれより前の最後の 30 日平均を比べる。

    end より前 TREND_DAYS 日のうちに測定がない（最新が古すぎる）か、比べる相手の測定が
    なければ None。points は vo2max_trend の返り値（日付の順）。
    """
    known = [p for p in points if p.day <= end]
    if not known or known[-1].day <= end - timedelta(days=TREND_DAYS):
        return None
    now = known[-1]
    before = [p for p in known if p.day <= now.day - timedelta(days=TREND_DAYS)]
    if not before:
        return None
    change = now.average - before[-1].average
    if change >= TREND_MIN_CHANGE:
        return Vo2maxTrend.UP
    if change <= -TREND_MIN_CHANGE:
        return Vo2maxTrend.DOWN
    return Vo2maxTrend.FLAT
