from dataclasses import replace
from datetime import date, timedelta

import pytest

from app.domain.fallback_review import fallback_review
from app.domain.situation import Situation, WeekSituation

MONDAY = date(2026, 9, 28)

BASE = WeekSituation(
    situation=Situation.STEADY,
    start=MONDAY,
    end=MONDAY + timedelta(days=6),
    fitness=20.0,
    fatigue=22.0,
    headroom=-2.0,
    headroom_ratio=-0.1,
    workouts=3,
    total_sec=9000,
    unknown_load_days=0,
    rest_days_before=1,
    workouts_change=0,
    total_sec_change=0,
    fitness_change=0.5,
    fatigue_change=0.5,
)


def week(situation: Situation, **changes: object) -> WeekSituation:
    return replace(BASE, situation=situation, **changes)  # type: ignore[arg-type]


def words(text: str) -> int:
    return len(text.split())


@pytest.mark.parametrize("situation", list(Situation))
def test_every_situation_has_a_script_of_about_15_seconds(situation: Situation) -> None:
    """声に出して 15 秒ほど。試作のプロンプトと同じ 28〜40 語。"""
    review = fallback_review(week(situation, rest_days_before=20))

    assert 28 <= words(review.script) <= 40


@pytest.mark.parametrize("situation", list(Situation))
def test_every_situation_has_two_or_three_short_options(situation: Situation) -> None:
    """ボタンは 2〜4 語、その下の説明は 14 語まで。同じ振り返りに同じ文字のボタンを並べない。"""
    options = fallback_review(week(situation, rest_days_before=20)).options

    assert 2 <= len(options) <= 3
    assert all(2 <= words(o.label) <= 4 for o in options)
    assert all(words(o.description) <= 14 for o in options)
    assert len({o.label for o in options}) == len(options)


@pytest.mark.parametrize("situation", list(Situation))
def test_scripts_do_not_use_jargon_or_raw_load_values(situation: Situation) -> None:
    """専門用語を使わず、体力と疲労の値も読み上げない。"""
    review = fallback_review(week(situation, fitness=19.6, fatigue=27.4, rest_days_before=16))
    text = " ".join([review.script, *(f"{o.label} {o.description}" for o in review.options)])

    for term in ("TSS", "CTL", "ATL", "TSB", "PMC", "TRIMP"):
        assert term not in text
    for value in ("19", "27"):
        assert value not in text


@pytest.mark.parametrize("situation", list(Situation))
def test_every_situation_offers_a_gentle_option(situation: Situation) -> None:
    """どの週にも、休むか軽く流す選択肢がある。"""
    labels = {o.label for o in fallback_review(week(situation, rest_days_before=20)).options}

    gentle = {
        "Keep it easy",
        "Rest a bit more",
        "Rest when needed",
        "Rest fully",
        "Go easy",
        "Stay easy",
        "Go a bit easier",
    }
    assert labels & gentle


def test_fatigued_week_offers_nothing_that_adds_load() -> None:
    """疲労が溜まっている週には、強度や量を上げる選択肢を出さない。"""
    options = fallback_review(week(Situation.FATIGUED)).options
    text = " ".join(f"{o.label} {o.description}" for o in options).lower()

    for word in ("add", "more time", "harder", "push", "extra"):
        assert word not in text


def test_steady_week_says_the_count_and_minutes() -> None:
    """回数と合計の分は、コードで数えた値をそのまま入れる。分は四捨五入。"""
    script = fallback_review(week(Situation.STEADY, workouts=3, total_sec=9030)).script

    assert "You did 3 sessions in 151 minutes" in script


def test_steady_week_with_one_session_uses_the_singular() -> None:
    script = fallback_review(week(Situation.STEADY, workouts=1, total_sec=60)).script

    assert "You did 1 session in 1 minute," in script


def test_returning_week_says_how_many_days_off() -> None:
    script = fallback_review(week(Situation.RETURNING, rest_days_before=16)).script

    assert "after 16 days off" in script


def test_returning_week_without_rest_days_is_a_bug() -> None:
    """中断明けなのに休んだ日数がないのは、判定と材料の食い違い。黙って話さない。"""
    with pytest.raises(AssertionError):
        fallback_review(week(Situation.RETURNING, rest_days_before=None))


def test_not_enough_data_with_sessions_says_the_count() -> None:
    script = fallback_review(week(Situation.NOT_ENOUGH_DATA, workouts=2)).script

    assert "This week you did 2 sessions. Keep going," in script


def test_not_enough_data_before_the_first_session_does_not_say_zero() -> None:
    """まだ 1 件も記録がないときに「0 sessions」とは言わない。"""
    script = fallback_review(week(Situation.NOT_ENOUGH_DATA, workouts=0)).script

    assert "0 session" not in script
    assert "There are no sessions in yet." in script
