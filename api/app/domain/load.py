"""ワークアウトの負荷と、体力・疲労・余力の推移。

DB もタイムゾーンも持ち込まない純粋関数だけを置く。心拍の列と設定を受け取り、数値を返す。
日付の区切り（どのワークアウトがどの日か）は、呼ぶ側が利用者のタイムゾーンで決める。
"""

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

# Banister の TRIMP の係数。Banister EW. "Modeling elite athletic performance" (1991)、
# Morton RH, Fitz-Clarke JR, Banister EW. J Appl Physiol 69(3):1171-1177 (1990) の男性の値。
# 女性は 0.86 と 1.67 だが、users は性別を持たないので男性の値に固定する
TRIMP_A = 0.64
TRIMP_B = 1.92

# 体力と疲労の時定数（日）。Banister のインパルス応答モデルで広く使われる値で、
# Intervals.icu の Fitness / Fatigue の既定値とも同じ（42 日と 7 日）
FITNESS_DAYS = 42
FATIGUE_DAYS = 7


@dataclass(frozen=True)
class ZoneTimes:
    """強度ごとの時間（秒）。合計はワークアウトの duration_sec と一致する。"""

    low: int
    mid: int
    high: int


@dataclass(frozen=True)
class WorkoutLoad:
    """1 回ぶんの負荷と強度ごとの時間。散布図は load と zones.high を使う。

    load は最大心拍と安静時心拍、zones は境目 2 つがそろわないと None。
    心拍の記録がなければ両方 None。
    """

    load: float | None
    zones: ZoneTimes | None


@dataclass(frozen=True)
class DailyLoad:
    """その日の負荷。負荷の分からないワークアウトが 1 件でもあれば None。"""

    day: date
    load: float | None


@dataclass(frozen=True)
class FitnessPoint:
    """その日の終わりの体力・疲労・余力。余力は体力から疲労を引いた値。

    load が None の日は、負荷の分からないワークアウトを含む。体力と疲労は、その日の負荷を
    0 として計算しているので、実際より低く出る。画面ではその日に印を付ける。
    """

    day: date
    load: float | None
    fitness: float
    fatigue: float
    headroom: float


def sample_seconds(n_samples: int, duration_sec: int) -> float:
    """心拍 1 サンプルが受け持つ秒数。duration をサンプル数で均等に割る。

    心拍は 1 分ごとの区切り（14:10:00、14:11:00…）で届くが、最初と最後の区切りは
    ワークアウトの途中から・途中までしか含まず、一時停止の時間は duration に入らない。
    そのため 60 秒の決め打ちだと合計が duration とずれる（72 サンプルで 4320 秒に対し、
    duration は 4028 秒）。均等に割れば合計が duration と一致する。
    """
    if n_samples == 0:
        return 0.0
    return duration_sec / n_samples


def trimp(
    avg_bpms: Sequence[float], duration_sec: int, max_hr: int | None, resting_hr: int | None
) -> float | None:
    """Banister の TRIMP。サンプルごとに 分 × HRr × a × e^(b × HRr) を足す。

    HRr（心拍予備率）は (心拍 − 安静時) / (最大 − 安静時) で、0 から 1 に収める。
    最大心拍か安静時心拍が未設定なら計算しない（None）。心拍の記録がないときも None。
    0 を返すと、運動した日が休養日と同じ負荷になり、体力と疲労を低く見積もるため。
    """
    if not avg_bpms or max_hr is None or resting_hr is None or max_hr <= resting_hr:
        return None
    minutes = sample_seconds(len(avg_bpms), duration_sec) / 60
    reserve = max_hr - resting_hr
    total = 0.0
    for bpm in avg_bpms:
        hrr = min(max((bpm - resting_hr) / reserve, 0.0), 1.0)
        total += minutes * hrr * TRIMP_A * math.exp(TRIMP_B * hrr)
    return total


def zone_times(
    avg_bpms: Sequence[float], duration_sec: int, boundary_1: int | None, boundary_2: int | None
) -> ZoneTimes | None:
    """強度ごとの時間。boundary_1 未満は low、boundary_2 未満は mid、それ以上は high。

    サンプル数の比で duration を配る。秒は整数にし、端数は大きい順に 1 秒ずつ足して
    合計を duration にそろえる。境目が 2 つそろうまでは計算しない（None）。
    心拍の記録がないときも、どの強度だったか分からないので None。
    """
    if not avg_bpms or boundary_1 is None or boundary_2 is None:
        return None
    counts = [0, 0, 0]
    for bpm in avg_bpms:
        if bpm < boundary_1:
            counts[0] += 1
        elif bpm < boundary_2:
            counts[1] += 1
        else:
            counts[2] += 1
    n = len(avg_bpms)
    exact = [c * duration_sec / n for c in counts]
    secs = [math.floor(x) for x in exact]
    by_remainder = sorted(range(3), key=lambda i: exact[i] - secs[i], reverse=True)
    for i in by_remainder[: duration_sec - sum(secs)]:
        secs[i] += 1
    return ZoneTimes(low=secs[0], mid=secs[1], high=secs[2])


def workout_load(
    avg_bpms: Sequence[float],
    duration_sec: int,
    *,
    max_hr: int | None,
    resting_hr: int | None,
    boundary_1: int | None,
    boundary_2: int | None,
) -> WorkoutLoad:
    """1 回ぶんの負荷と強度ごとの時間をまとめて出す。"""
    return WorkoutLoad(
        load=trimp(avg_bpms, duration_sec, max_hr, resting_hr),
        zones=zone_times(avg_bpms, duration_sec, boundary_1, boundary_2),
    )


def daily_loads(
    loads: Iterable[tuple[date, float | None]], start: date, end: date
) -> list[DailyLoad]:
    """日ごとの負荷。同じ日のワークアウトは足し、記録のない日は 0。start から end まで両端を含む。

    loads の日付は、呼ぶ側が利用者のタイムゾーンで決めたもの。範囲の外は捨てる。
    負荷が None（心拍の記録がないなど）のワークアウトは省かずに渡す。省くと、運動した日が
    休養日と同じ 0 になる。1 件でも None があれば、その日の負荷は None（分からない）。
    """
    totals: dict[date, float | None] = {}
    for day, load in loads:
        if start <= day <= end:
            known = totals.get(day, 0.0)
            totals[day] = None if known is None or load is None else known + load
    days = (end - start).days + 1
    return [
        DailyLoad(day=d, load=totals.get(d, 0.0))
        for d in (start + timedelta(days=i) for i in range(days))
    ]


def _decay(days: int) -> float:
    """1 日で前日の値をどれだけ残すか。Banister のモデルの e^(−1/τ)。"""
    return math.exp(-1 / days)


def fitness_fatigue(
    daily: Sequence[DailyLoad], fitness_start: float = 0.0, fatigue_start: float = 0.0
) -> list[FitnessPoint]:
    """日ごとの負荷から、体力（42 日）と疲労（7 日）の指数移動平均を出す。

    値_t = 値_(t−1) × k + 負荷_t × (1 − k)、k = e^(−1/τ)。
    初日の前の値は fitness_start と fatigue_start（既定 0）。表示の期間より前から
    渡しておくと、期間の初日が 0 から立ち上がらずにすむ。

    負荷が None の日は 0 として計算を続ける。線を途切れさせないためで、その日の点の
    load は None のまま返す。止める（前日の値のまま）のも、以降を出さないのも選ばない。
    心拍の欠けはまれで、1 件のために以降のグラフを失うより、印を付けて見せる方がよい。
    """
    kf = _decay(FITNESS_DAYS)
    kg = _decay(FATIGUE_DAYS)
    fitness = fitness_start
    fatigue = fatigue_start
    points = []
    for d in daily:
        load = 0.0 if d.load is None else d.load
        fitness = fitness * kf + load * (1 - kf)
        fatigue = fatigue * kg + load * (1 - kg)
        points.append(
            FitnessPoint(
                day=d.day, load=d.load, fitness=fitness, fatigue=fatigue, headroom=fitness - fatigue
            )
        )
    return points
