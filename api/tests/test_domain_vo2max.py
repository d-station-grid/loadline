from datetime import date

import pytest

from app.domain.vo2max import Vo2maxPoint, Vo2maxTrend, vo2max_trend, vo2max_trend_until


def test_vo2max_trend_averages_last_30_days() -> None:
    # README の休養前後（46.7 から 44.7）を模した並び。日付は順不同で渡す
    readings = [
        (date(2026, 9, 5), 44.7),
        (date(2026, 7, 1), 46.7),
        (date(2026, 7, 20), 46.5),
        (date(2026, 7, 30), 46.3),
    ]

    points = vo2max_trend(readings)

    assert [p.day for p in points] == [
        date(2026, 7, 1),
        date(2026, 7, 20),
        date(2026, 7, 30),
        date(2026, 9, 5),
    ]
    assert [p.value for p in points] == [46.7, 46.5, 46.3, 44.7]
    # 7/30 は 7/1〜7/30 の 3 回: (46.7 + 46.5 + 46.3) / 3 = 46.5
    assert points[2].average == pytest.approx(46.5)
    # 9/5 の窓は 8/7 から。入るのは自分だけ
    assert points[3].average == pytest.approx(44.7)


def test_vo2max_trend_window_includes_day_29_back() -> None:
    # 30 日目の 7/31 は 7/2 から。7/1 は外れ、7/2 は入る
    readings = [(date(2026, 7, 1), 40.0), (date(2026, 7, 2), 42.0), (date(2026, 7, 31), 44.0)]

    last = vo2max_trend(readings)[-1]

    assert last.average == pytest.approx(43.0)


def test_vo2max_trend_empty() -> None:
    assert vo2max_trend([]) == []


def _points(*days_and_averages: tuple[date, float]) -> list[Vo2maxPoint]:
    return [Vo2maxPoint(day=d, value=a, average=a) for d, a in days_and_averages]


END = date(2026, 10, 18)


@pytest.mark.parametrize(
    ("before", "now", "trend"),
    [
        (45.0, 45.5, Vo2maxTrend.UP),
        (45.0, 45.4, Vo2maxTrend.FLAT),
        (45.0, 44.6, Vo2maxTrend.FLAT),
        (45.0, 44.5, Vo2maxTrend.DOWN),
    ],
)
def test_trend_compares_the_30_day_averages_four_weeks_apart(
    before: float, now: float, trend: Vo2maxTrend
) -> None:
    """最新の平均と、その 28 日前かそれより前の最後の平均を比べる。差が 0.5 未満は横ばい。"""
    points = _points(
        (date(2026, 9, 10), 40.0),
        (date(2026, 9, 15), before),
        # 28 日前より後なので、比べる相手にはならない
        (date(2026, 9, 20), 50.0),
        (date(2026, 10, 13), now),
    )

    assert vo2max_trend_until(points, END) is trend


def test_trend_ignores_readings_after_the_week() -> None:
    """週の最終日より後の測定は使わない。作る日によって傾向が変わらないため。"""
    points = _points(
        (date(2026, 9, 15), 45.0),
        (date(2026, 10, 13), 45.0),
        (date(2026, 10, 19), 48.0),
    )

    assert vo2max_trend_until(points, END) is Vo2maxTrend.FLAT


def test_trend_needs_a_recent_reading_and_one_four_weeks_before() -> None:
    # 比べる相手がない
    assert vo2max_trend_until(_points((date(2026, 10, 13), 45.0)), END) is None
    # 最新が週の最終日の 28 日前かそれより前で、古すぎる
    old = _points((date(2026, 8, 1), 44.0), (date(2026, 9, 20), 45.0))
    assert vo2max_trend_until(old, END) is None
    assert vo2max_trend_until([], END) is None
