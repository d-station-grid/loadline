import json
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pytest

from app.domain.vo2max import vo2max_trend
from app.services.ingest import is_apple_watch, parse_time

SAMPLE = Path(__file__).parent / "fixtures" / "sample_health-auto-export_vo2max.json"


def _sample_readings() -> list[tuple[date, float]]:
    """spike で受け取った実データ（7/5〜9/21）。取り込みと同じく Apple Watch だけを、小数 1 桁で。

    日付は +0900 のまま取る。Asia/Tokyo の利用者の区切りと同じ。
    """
    points = json.loads(SAMPLE.read_text())["data"]["metrics"][0]["data"]
    return [
        (
            parse_time(p["date"]).date(),
            float(Decimal(str(p["qty"])).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)),
        )
        for p in points
        if is_apple_watch(p["source"])
    ]


def test_vo2max_trend_of_sample_readings() -> None:
    points = vo2max_trend(_sample_readings())

    # Google Health の 65 件は入らず、Apple Watch の 17 件だけ
    assert len(points) == 17
    assert (points[0].day, points[0].value, points[0].average) == (date(2026, 7, 5), 46.5, 46.5)
    # 休養の前は 46.7、休養のあとは 44.7 まで落ちる（README の 2 章）
    assert max(p.value for p in points) == 46.7
    assert min(p.value for p in points) == 44.7

    by_day = {p.day: p for p in points}
    # 8/14 の窓は 7/16〜8/14 の 8 回
    # (46.7 + 46.6 + 46.2 + 45.8 + 45.5 + 45.3 + 45.2 + 44.7) / 8 = 366.0 / 8 = 45.75
    assert by_day[date(2026, 8, 14)].average == pytest.approx(45.75)
    # 9/18 の窓は 8/20〜9/18 の 7 回
    # (44.7 + 44.9 + 44.9 + 44.9 + 45.1 + 45.1 + 45.7) / 7 = 315.3 / 7 = 45.04286
    assert by_day[date(2026, 9, 18)].average == pytest.approx(45.04286, abs=1e-5)


def test_vo2max_trend_of_sample_readings_same_day() -> None:
    # 8/5 は 2 回測っている（45.8 と 45.5）。どちらの平均にも両方が入る
    # 窓は 7/7〜8/5 の 6 回: (46.7 + 46.7 + 46.6 + 46.2 + 45.8 + 45.5) / 6 = 277.5 / 6 = 46.25
    same_day = [p for p in vo2max_trend(_sample_readings()) if p.day == date(2026, 8, 5)]

    assert [p.value for p in same_day] == [45.8, 45.5]
    assert [p.average for p in same_day] == [pytest.approx(46.25)] * 2


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
