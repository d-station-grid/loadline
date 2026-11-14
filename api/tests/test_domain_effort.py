import pytest

from app.domain.effort import (
    HEAVY_FROM,
    HISTORY_WEEKS,
    LIGHT_BELOW,
    MIN_HISTORY_WEEKS,
    NO_EFFORT,
    Effort,
    PastWeek,
    Volume,
    judge_effort,
)
from app.domain.load import ZoneTimes

# 普段の週。負荷 100、高強度 600 秒
USUAL = PastWeek(load=100.0, high_sec=600)
EASY = ZoneTimes(low=6000, mid=1200, high=600)


def history(weeks: int = HISTORY_WEEKS, week: PastWeek = USUAL) -> list[PastWeek]:
    return [week] * weeks


def judge(
    load: float = 100.0,
    unknown_load_days: int = 0,
    zones: ZoneTimes | None = EASY,
    past: list[PastWeek] | None = None,
) -> Effort:
    return judge_effort(load, unknown_load_days, zones, history() if past is None else past)


@pytest.mark.parametrize(
    ("load", "volume"),
    [
        (0.0, Volume.LIGHT),
        (100 * LIGHT_BELOW - 0.1, Volume.LIGHT),
        (100 * LIGHT_BELOW, Volume.USUAL),
        (100.0, Volume.USUAL),
        # 1.4〜1.5 は「いつもどおり」に寄せる
        (100 * HEAVY_FROM - 0.1, Volume.USUAL),
        (100 * HEAVY_FROM, Volume.HEAVY),
    ],
)
def test_volume_compares_the_load_with_the_usual_week(load: float, volume: Volume) -> None:
    effort = judge(load)

    assert effort.volume is volume
    assert effort.load_ratio == pytest.approx(load / 100)


def test_volume_uses_only_the_latest_weeks() -> None:
    """古い週は HISTORY_WEEKS 週より前なら使わない。"""
    past = [PastWeek(load=1000.0, high_sec=0)] + history()

    assert judge(100.0, past=past).volume is Volume.USUAL


def test_volume_uses_what_there_is_from_the_minimum_weeks() -> None:
    """過去が MIN_HISTORY_WEEKS 週以上あれば、ある分の平均で比べる。"""
    past = history(MIN_HISTORY_WEEKS, PastWeek(load=50.0, high_sec=0))

    effort = judge(100.0, past=past)

    assert effort.volume is Volume.HEAVY
    assert effort.load_ratio == pytest.approx(2.0)


@pytest.mark.parametrize(
    ("unknown_load_days", "past"),
    [
        pytest.param(0, history(MIN_HISTORY_WEEKS - 1), id="short_history"),
        pytest.param(1, history(), id="missing_heart_rate"),
        pytest.param(0, history(week=PastWeek(load=0.0, high_sec=0)), id="no_past_load"),
    ],
)
def test_volume_is_not_judged_without_enough_to_compare(
    unknown_load_days: int, past: list[PastWeek]
) -> None:
    effort = judge(unknown_load_days=unknown_load_days, past=past)

    assert effort.volume is None
    assert effort.load_ratio is None
    assert effort.hard_went_up is False


@pytest.mark.parametrize(
    ("zones", "mostly_moderate"),
    [
        (ZoneTimes(low=3000, mid=3001, high=0), True),
        (ZoneTimes(low=3000, mid=3000, high=0), False),
        (EASY, False),
        (None, False),
    ],
)
def test_mostly_moderate_when_moderate_is_longer_than_easy(
    zones: ZoneTimes | None, mostly_moderate: bool
) -> None:
    """中強度寄りは、量を判定できない週でも、強度の時間が分かれば判定する。"""
    assert judge(zones=zones, past=[]).mostly_moderate is mostly_moderate


def test_hard_went_up_when_hard_time_grew_more_than_the_load() -> None:
    # 負荷は 2 倍、高強度は 600 → 1800 秒で 3 倍
    effort = judge(200.0, zones=ZoneTimes(low=6000, mid=1200, high=1800))

    assert effort.volume is Volume.HEAVY
    assert effort.hard_went_up is True


def test_no_hard_went_up_when_hard_time_grew_less_than_the_load() -> None:
    # 負荷は 2 倍、高強度は 600 → 900 秒で 1.5 倍。増えたのは主に低・中強度
    effort = judge(200.0, zones=ZoneTimes(low=12000, mid=2400, high=900))

    assert effort.volume is Volume.HEAVY
    assert effort.hard_went_up is False


def test_hard_time_is_not_judged_when_there_was_none_before() -> None:
    """過去の高強度が 0 分なら、比べる基準がないので判定しない。0 分から 1 分になっただけで
    「高強度の時間も増えた」と言わないため。"""
    past = history(week=PastWeek(load=100.0, high_sec=0))

    effort = judge(200.0, zones=ZoneTimes(low=6000, mid=0, high=60), past=past)

    assert effort.volume is Volume.HEAVY
    assert effort.hard_went_up is False


def test_no_hard_went_up_unless_the_volume_is_heavy() -> None:
    """高強度の割合が高くても、量が普段どおりなら判定しない。"""
    effort = judge(100.0, zones=ZoneTimes(low=600, mid=0, high=3000))

    assert effort.volume is Volume.USUAL
    assert effort.hard_went_up is False


def test_no_hard_went_up_without_zones() -> None:
    assert judge(200.0, zones=None).hard_went_up is False


def test_no_effort_judges_nothing() -> None:
    assert NO_EFFORT == Effort(
        volume=None, load_ratio=None, mostly_moderate=False, hard_went_up=False
    )
