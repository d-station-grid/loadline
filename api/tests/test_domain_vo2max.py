from datetime import date

import pytest

from app.domain.vo2max import Vo2maxTrend, vo2max_trend, vo2max_trend_of


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


@pytest.mark.parametrize(
    ("change", "trend"),
    [
        (0.5, Vo2maxTrend.UP),
        (0.4, Vo2maxTrend.FLAT),
        (-0.4, Vo2maxTrend.FLAT),
        (-0.5, Vo2maxTrend.DOWN),
        (-3.5, Vo2maxTrend.DOWN),
        (None, None),
    ],
)
def test_trend_classifies_the_change_shown_on_the_card(
    change: float | None, trend: Vo2maxTrend | None
) -> None:
    """カードと同じ差を 0.5 で区分する。差が 0.5 未満は横ばい。"""
    assert vo2max_trend_of(change) is trend
