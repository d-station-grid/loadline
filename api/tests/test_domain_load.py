import json
from datetime import date
from pathlib import Path

import pytest

from app.domain.apple_health import is_apple_watch
from app.domain.load import (
    DailyLoad,
    WorkoutLoad,
    ZoneTimes,
    daily_loads,
    fitness_fatigue,
    sample_seconds,
    total_zones,
    trimp,
    workout_load,
    zone_times,
)

SAMPLE = Path(__file__).parent / "fixtures" / "sample_health-auto-export_workouts-v2.json"


def _sample_workout() -> tuple[list[int], int]:
    """fixtures の実データのうち、取り込まれる方（Apple Watch）の心拍と duration。

    DB に入るときと同じく、心拍は整数に丸め、duration も秒に丸める。
    """
    data = json.loads(SAMPLE.read_text())["data"]["workouts"]
    w = next(w for w in data if is_apple_watch(w["source"]["name"]))
    return [round(p["Avg"]) for p in w["heartRateData"]], round(w["duration"])


# --- 1 サンプルの秒数 ---


def test_sample_seconds_splits_duration_evenly() -> None:
    assert sample_seconds(72, 4028) == pytest.approx(55.9444, abs=1e-4)
    assert sample_seconds(0, 4028) == 0


# --- TRIMP ---


def test_trimp_by_hand() -> None:
    # 60 分ずっと HRr 0.5（安静 50、最大 170 で 110bpm）
    # 60 × 0.5 × 0.64 × e^(1.92 × 0.5) = 19.2 × 2.61170 = 50.1446
    bpms = [110] * 60
    assert trimp(bpms, 3600, 170, 50) == pytest.approx(50.1446, abs=1e-4)


def test_trimp_clamps_heart_rate_reserve() -> None:
    # 安静時より低い心拍は 0、最大を超える心拍は 1 として数える
    assert trimp([40], 60, 170, 50) == 0
    assert trimp([200], 60, 170, 50) == pytest.approx(0.64 * 6.82096, abs=1e-4)


def test_trimp_is_none_without_settings() -> None:
    assert trimp([110], 60, None, 50) is None
    assert trimp([110], 60, 170, None) is None


def test_trimp_is_none_without_heart_rates() -> None:
    # 心拍の記録がない 60 分のワークアウト。0 にすると休養日と区別できない
    assert trimp([], 3600, 175, 50) is None


def test_workout_load_is_none_without_heart_rates() -> None:
    point = workout_load([], 3600, max_hr=175, resting_hr=50, boundary_1=130, boundary_2=155)
    assert point.load is None
    assert point.zones is None


def test_trimp_of_sample_workout() -> None:
    # 72 サンプル、4028 秒、最大 175・安静 50。各サンプル 55.94 秒で足したもの
    bpms, duration = _sample_workout()
    assert (len(bpms), duration) == (72, 4028)
    assert trimp(bpms, duration, 175, 50) == pytest.approx(86.6686, abs=1e-4)


# --- 強度ごとの時間 ---


def test_zone_times_splits_by_boundaries() -> None:
    bpms = [100, 129, 130, 154, 155, 170]

    assert zone_times(bpms, 360, 130, 155) == ZoneTimes(low=120, mid=120, high=120)


def test_zone_times_is_none_without_boundaries() -> None:
    assert zone_times([100], 60, None, 155) is None
    assert zone_times([100], 60, 130, None) is None


def test_zone_times_of_sample_workout_sum_to_duration() -> None:
    # low 50、mid 21、high 1 サンプル。4028 / 72 秒ずつで 2797.22、1174.83、55.94。
    # 切り捨てると 4026 秒で、端数の大きい high と mid に 1 秒ずつ足す
    bpms, duration = _sample_workout()

    zones = zone_times(bpms, duration, 130, 155)

    assert zones == ZoneTimes(low=2797, mid=1175, high=56)
    assert zones.low + zones.mid + zones.high == duration


def test_zone_times_is_none_without_heart_rates() -> None:
    assert zone_times([], 600, 130, 155) is None


def test_workout_load_for_scatter() -> None:
    bpms, duration = _sample_workout()

    point = workout_load(bpms, duration, max_hr=175, resting_hr=50, boundary_1=130, boundary_2=155)

    assert point.load == pytest.approx(86.6686, abs=1e-4)
    assert point.zones is not None
    assert point.zones.high == 56


def test_workout_load_keeps_what_settings_allow() -> None:
    point = workout_load([110], 60, max_hr=None, resting_hr=None, boundary_1=130, boundary_2=155)
    assert point.load is None
    assert point.zones == ZoneTimes(low=60, mid=0, high=0)


def test_total_zones_sums_each_zone() -> None:
    loads = [
        WorkoutLoad(load=1.0, zones=ZoneTimes(low=60, mid=30, high=10)),
        WorkoutLoad(load=2.0, zones=ZoneTimes(low=5, mid=0, high=20)),
    ]
    assert total_zones(loads) == ZoneTimes(low=65, mid=30, high=30)


def test_total_zones_is_none_when_a_workout_has_no_heart_rate() -> None:
    loads = [
        WorkoutLoad(load=1.0, zones=ZoneTimes(low=60, mid=30, high=10)),
        WorkoutLoad(load=None, zones=None),
    ]
    assert total_zones(loads) is None


def test_total_zones_without_workouts_is_zero() -> None:
    assert total_zones([]) == ZoneTimes(low=0, mid=0, high=0)


# --- 日ごとの負荷 ---


def test_daily_loads_sums_same_day_and_fills_empty_days() -> None:
    loads = [
        (date(2026, 9, 13), 40.0),
        (date(2026, 9, 13), 10.0),
        (date(2026, 9, 15), 30.0),
        (date(2026, 9, 20), 99.0),  # 範囲の外
    ]

    daily = daily_loads(loads, date(2026, 9, 12), date(2026, 9, 15))

    assert daily == [
        DailyLoad(date(2026, 9, 12), 0.0),
        DailyLoad(date(2026, 9, 13), 50.0),
        DailyLoad(date(2026, 9, 14), 0.0),
        DailyLoad(date(2026, 9, 15), 30.0),
    ]


# --- 体力・疲労・余力 ---


def test_daily_loads_is_none_when_any_workout_is_unknown() -> None:
    # 9/13 は 2 件のうち 1 件が分からない。足せる方だけ足すと低く出るので、その日は None
    # 9/14 は分からない 1 件だけ。省くと 0（休養日）になってしまう
    loads: list[tuple[date, float | None]] = [
        (date(2026, 9, 13), 40.0),
        (date(2026, 9, 13), None),
        (date(2026, 9, 14), None),
        (date(2026, 9, 15), 30.0),
    ]

    daily = daily_loads(loads, date(2026, 9, 13), date(2026, 9, 16))

    assert [d.load for d in daily] == [None, None, 30.0, 0.0]


def test_fitness_fatigue_carries_on_through_unknown_day() -> None:
    # 分からない日は 0 として計算を続け、点の load は None のまま返す
    known = [DailyLoad(date(2026, 9, 13), 100.0), DailyLoad(date(2026, 9, 14), 0.0)]
    unknown = [DailyLoad(date(2026, 9, 13), 100.0), DailyLoad(date(2026, 9, 14), None)]

    expected = fitness_fatigue(known)
    points = fitness_fatigue(unknown)

    assert points[1].load is None
    assert points[1].fitness == pytest.approx(expected[1].fitness)
    assert points[1].fatigue == pytest.approx(expected[1].fatigue)
    assert points[1].headroom == pytest.approx(expected[1].headroom)


def test_fitness_fatigue_by_hand() -> None:
    # 初日に 100、翌日は 0
    # 体力: 100 × (1 − e^(−1/42)) = 2.35283、翌日 × e^(−1/42) = 2.29747
    # 疲労: 100 × (1 − e^(−1/7)) = 13.31221、翌日 × e^(−1/7) = 11.54006
    daily = [DailyLoad(date(2026, 9, 13), 100.0), DailyLoad(date(2026, 9, 14), 0.0)]

    first, second = fitness_fatigue(daily)

    assert first.fitness == pytest.approx(2.35283, abs=1e-5)
    assert first.fatigue == pytest.approx(13.31221, abs=1e-5)
    assert first.headroom == pytest.approx(2.35283 - 13.31221, abs=1e-5)
    assert second.fitness == pytest.approx(2.29747, abs=1e-5)
    assert second.fatigue == pytest.approx(11.54006, abs=1e-5)
    assert second.load == 0


def test_fitness_fatigue_settles_on_steady_load() -> None:
    # 同じ負荷を続けると、体力も疲労もその値に近づき、余力は 0 に近づく
    daily = [DailyLoad(date(2026, 1, 1), 50.0)] * 400

    last = fitness_fatigue(daily)[-1]

    assert last.fitness == pytest.approx(50.0, abs=0.01)
    assert last.fatigue == pytest.approx(50.0, abs=1e-6)
    assert last.headroom == pytest.approx(0.0, abs=0.01)


def test_fitness_fatigue_continues_from_start_values() -> None:
    daily = [DailyLoad(date(2026, 9, 13), 0.0)]

    (point,) = fitness_fatigue(daily, fitness_start=40.0, fatigue_start=60.0)

    assert point.fitness == pytest.approx(40.0 * 0.9764717, abs=1e-5)
    assert point.fatigue == pytest.approx(60.0 * 0.8668779, abs=1e-5)
