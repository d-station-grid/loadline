from dataclasses import replace
from datetime import date, timedelta

import pytest

from app.domain.fallback_review import fallback_review
from app.domain.load import FitnessPoint
from app.domain.situation import Situation, WeekInput, WeekSituation, judge_week

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


# 判定が「疲労」より先に当てる状況と「疲労」。どれも疲労が高いことがある
MAY_BE_TIRED = [
    Situation.NOT_ENOUGH_DATA,
    Situation.NO_TRAINING,
    Situation.RETURNING,
    Situation.FATIGUED,
]
ADDS_LOAD = ("add", "more time", "harder", "push", "extra", "one more")

# 記録が足りない週の 3 つの言い方: 記録がない、心拍のない日がある、記録が短いか体力が 0
NOT_ENOUGH_DATA_WEEKS = [
    pytest.param({"workouts": 0}, id="no_sessions"),
    pytest.param({"unknown_load_days": 1}, id="missing_heart_rate"),
    pytest.param({}, id="short_history"),
]


def adds_load(review_text: str) -> list[str]:
    return [w for w in ADDS_LOAD if w in review_text.lower()]


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


@pytest.mark.parametrize("situation", MAY_BE_TIRED)
def test_tired_weeks_offer_nothing_that_adds_load(situation: Situation) -> None:
    """疲労が高い週には、強度や量を上げる選択肢を出さない。余力 ÷ 体力 が −75% の週で見る。"""
    tired = week(
        situation,
        fitness=20.0,
        fatigue=35.0,
        headroom=-15.0,
        headroom_ratio=-0.75,
        rest_days_before=14,
    )
    options = fallback_review(tired).options

    assert adds_load(" ".join(f"{o.label} {o.description}" for o in options)) == []


def test_returning_after_a_break_with_high_fatigue_offers_nothing_that_adds_load() -> None:
    """14 日休んで再開し、週末に体力 20・疲労 35。判定は疲労より中断明けを先に当てる。"""
    sunday = MONDAY + timedelta(days=6)
    situation = judge_week(
        WeekInput(
            start=MONDAY,
            first_workout_day=date(2026, 6, 1),
            last_workout_day_before=MONDAY - timedelta(days=15),
            workout_days=[MONDAY, MONDAY + timedelta(days=2), MONDAY + timedelta(days=4)],
            total_sec=10800,
            unknown_load_days=0,
            end=FitnessPoint(day=sunday, load=0.0, fitness=20.0, fatigue=35.0, headroom=-15.0),
            previous=None,
        )
    )
    assert situation.situation == Situation.RETURNING
    assert situation.rest_days_before == 14

    options = fallback_review(situation).options

    assert adds_load(" ".join(f"{o.label} {o.description}" for o in options)) == []


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
    """中断明けなのに休んだ日数がないのは、判定と材料の食い違い。「None days」とは話さない。"""
    with pytest.raises(ValueError, match="rest_days_before"):
        fallback_review(week(Situation.RETURNING, rest_days_before=None))


@pytest.mark.parametrize("changes", NOT_ENOUGH_DATA_WEEKS)
def test_not_enough_data_scripts_are_about_15_seconds(changes: dict[str, int]) -> None:
    script = fallback_review(week(Situation.NOT_ENOUGH_DATA, **changes)).script

    assert 28 <= words(script) <= 40


def test_not_enough_data_before_the_first_session() -> None:
    """まだ 1 件も記録がないときに「0 sessions」とは言わない。"""
    script = fallback_review(week(Situation.NOT_ENOUGH_DATA, workouts=0)).script

    assert script == (
        "I'm still getting to know your training. "
        "Fitness takes about six weeks of records to read well. "
        "There are no sessions in yet. Once you start, I'll have more to tell you soon."
    )


def test_not_enough_data_with_missing_heart_rate_says_so() -> None:
    """心拍のない日がある週に「まだ 6 週間分ない」とは言わない。"""
    script = fallback_review(
        week(Situation.NOT_ENOUGH_DATA, workouts=2, unknown_load_days=1)
    ).script

    assert script.startswith("This week you did 2 sessions, but some of them have no heart rate")
    assert "six weeks" not in script


def test_not_enough_data_with_a_short_history_says_the_count() -> None:
    """記録が短いか体力が 0。判定の結果からはどちらか分からないので、どちらでも本当の言い方。"""
    script = fallback_review(week(Situation.NOT_ENOUGH_DATA, workouts=2)).script

    assert script.startswith("This week you did 2 sessions. I can't read your fitness")
    assert "six weeks" not in script
    assert "no heart rate" not in script


def test_scripts_do_not_overstate_what_the_numbers_show() -> None:
    """休んだ週に回復したとは、休めている週に疲労が下がったとは、言い切らない。"""
    no_training = fallback_review(week(Situation.NO_TRAINING, workouts=0)).script
    fresh = fallback_review(week(Situation.FRESH)).script

    assert "recover" not in no_training
    assert "dropped" not in fresh
