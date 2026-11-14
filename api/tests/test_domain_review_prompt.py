import json
from dataclasses import replace
from datetime import date, timedelta
from typing import Any

import pytest

from app.domain.effort import Effort, Volume
from app.domain.fallback_review import ReviewContent, ReviewOption
from app.domain.review_material import ReviewMaterial
from app.domain.review_prompt import (
    SYSTEM_INSTRUCTION,
    InvalidReviewError,
    NoteForReview,
    check_review,
    review_prompt,
)
from app.domain.situation import Situation, WeekSituation

MONDAY = date(2026, 10, 19)

BASE = WeekSituation(
    situation=Situation.STEADY,
    start=MONDAY,
    end=MONDAY + timedelta(days=6),
    fitness=19.6,
    fatigue=21.3,
    headroom=-1.7,
    headroom_ratio=-0.087,
    workouts=4,
    total_sec=13530,
    unknown_load_days=1,
    rest_days_before=2,
    workouts_change=1,
    total_sec_change=-1830,
    fitness_change=0.6,
    fatigue_change=0.9,
)

LINE = " ".join(["word"] * 30)
OPTIONS = (
    ReviewOption("Rest fully", "Take a few days off."),
    ReviewOption("Go easy", "Only easy sessions this week."),
)


def material(
    previous_choice: ReviewOption | None = None, effort: Effort | None = None, **changes: Any
) -> ReviewMaterial:
    m = ReviewMaterial(week=replace(BASE, **changes), previous_choice=previous_choice)
    return m if effort is None else replace(m, effort=effort)


HEAVY_HARD = Effort(volume=Volume.HEAVY, load_ratio=1.62, mostly_moderate=True, hard_spike=True)


def prompt_data(
    m: ReviewMaterial, notes: list[NoteForReview] | None = None, health_flag: bool = False
) -> Any:
    """本文の JSON の部分だけを読む。"""
    text = review_prompt(m, notes or [], health_flag=health_flag)
    return json.loads(text[text.index("{") :])


def test_prompt_passes_counts_minutes_and_changes_counted_by_code() -> None:
    """回数・分・休んだ日数・前の週との差は、コードで数えたものを渡す。分は四捨五入。"""
    data = prompt_data(material())

    assert data["situation"] == "steady"
    assert data["week"] == {"from": "2026-10-19", "to": "2026-10-25"}
    # 13530 秒 = 225.5 分 → 226。差の -1830 秒 = -30.5 分 → -31（0 から遠い側）
    assert data["this_week"] == {
        "sessions": 4,
        "minutes": 226,
        "days_with_sessions_missing_heart_rate": 1,
    }
    assert data["days_off_before_first_session"] == 2
    assert data["compared_with_last_week"] == {"sessions": 1, "minutes": -31}


def test_prompt_does_not_pass_fitness_or_fatigue_values() -> None:
    """体力と疲労の値は、単位のせいで誤解を招くので渡さない。"""
    text = review_prompt(material(), [], health_flag=False)

    for value in ("19.6", "21.3", "-1.7", "0.087", "0.6", "0.9"):
        assert value not in text


def test_prompt_has_no_comparison_without_a_previous_week() -> None:
    data = prompt_data(material(workouts_change=None, total_sec_change=None))

    assert data["compared_with_last_week"] is None


@pytest.mark.parametrize(
    ("situation", "may_offer_more"),
    [
        (Situation.FRESH, True),
        (Situation.STEADY, True),
        # 疲労と、疲労より先に当たる 3 つの状況では、量や強度を上げる選択肢を出さない
        (Situation.FATIGUED, False),
        (Situation.RETURNING, False),
        (Situation.NO_TRAINING, False),
        (Situation.NOT_ENOUGH_DATA, False),
    ],
)
def test_code_decides_whether_options_may_add_load(
    situation: Situation, may_offer_more: bool
) -> None:
    assert prompt_data(material(situation=situation))["may_offer_more"] is may_offer_more


@pytest.mark.parametrize("situation", list(Situation))
def test_health_flag_keeps_options_from_adding_load(situation: Situation) -> None:
    """痛みや病気に触れたメモがある週は、どの状況でも量や強度を上げる選択肢を出さない。"""
    data = prompt_data(material(situation=situation), health_flag=True)

    assert data["may_offer_more"] is False


def test_prompt_passes_the_effort_decided_by_code_without_the_ratio() -> None:
    """練習の量は区分だけを渡し、負荷の比の数値は渡さない。"""
    text = review_prompt(material(effort=HEAVY_HARD), [], health_flag=False)
    data = json.loads(text[text.index("{") :])

    assert data["effort"] == {
        "volume_vs_usual": "heavy",
        "mostly_moderate_intensity": True,
        "hard_efforts_jumped": True,
    }
    assert "1.62" not in text


def test_prompt_passes_null_when_the_volume_cannot_be_judged() -> None:
    assert prompt_data(material())["effort"] == {
        "volume_vs_usual": None,
        "mostly_moderate_intensity": False,
        "hard_efforts_jumped": False,
    }


@pytest.mark.parametrize("situation", [Situation.FRESH, Situation.STEADY])
def test_heavy_week_keeps_options_from_adding_load(situation: Situation) -> None:
    """普段より多めに練習した週は、休めている週や順調な週でも量を増やす選択肢を出さない。"""
    heavy = Effort(volume=Volume.HEAVY, load_ratio=1.6, mostly_moderate=False, hard_spike=False)

    assert prompt_data(material(situation=situation, effort=heavy))["may_offer_more"] is False


@pytest.mark.parametrize("volume", [Volume.LIGHT, Volume.USUAL, None])
def test_other_volumes_leave_rested_weeks_free_to_add_load(volume: Volume | None) -> None:
    effort = Effort(volume=volume, load_ratio=None, mostly_moderate=False, hard_spike=False)

    assert prompt_data(material(situation=Situation.FRESH, effort=effort))["may_offer_more"] is True


def test_system_instruction_explains_the_effort() -> None:
    for key in ("volume_vs_usual", "mostly_moderate_intensity", "hard_efforts_jumped"):
        assert f"`{key}`" in SYSTEM_INSTRUCTION
    assert "not as a mistake" in SYSTEM_INSTRUCTION


def test_system_instruction_replaces_moderate_sessions_instead_of_adding_easy_ones() -> None:
    """中強度寄りの選択肢は、置き換える形にする。足す形だと、量が多めの週に「増やすな」と
    ぶつかり、Jev に引っかかって定型に落ち、中強度の話が消えるため。"""
    assert "replaces some moderate sessions with easy ones" in SYSTEM_INSTRUCTION
    assert "Replace, do not add" in SYSTEM_INSTRUCTION
    assert "more easy sessions" not in SYSTEM_INSTRUCTION


def test_prompt_passes_the_previous_choice() -> None:
    choice = ReviewOption("Keep it steady", "Train the same way as last week.")

    assert prompt_data(material(choice))["last_choice"] == {
        "label": "Keep it steady",
        "description": "Train the same way as last week.",
    }
    assert prompt_data(material())["last_choice"] is None


def test_prompt_passes_notes_by_date_with_labels() -> None:
    notes = [
        NoteForReview(MONDAY + timedelta(days=4), None, "Legs heavy on the run."),
        NoteForReview(MONDAY + timedelta(days=1), "Work", "Deadline week. Slept badly."),
    ]

    assert prompt_data(material(), notes)["notes"] == [
        {"date": "2026-10-20", "label": "Work", "text": "Deadline week. Slept badly."},
        {"date": "2026-10-23", "label": None, "text": "Legs heavy on the run."},
    ]
    # メモを送らない設定のときは、呼ぶ側が空で渡す
    assert prompt_data(material(), [])["notes"] == []


def test_system_instruction_keeps_the_rules_of_the_fallback() -> None:
    """定型と同じ決まり（長さ、軽い選択肢、医療的な助言と専門用語なし）と、創作しない、英語で書く。"""
    for rule in (
        "28 to 40",
        "One option must always be the gentle one",
        "`may_offer_more` is false",
        "You are not a doctor",
        "TSS, CTL, ATL, TSB, PMC or TRIMP",
        "never give fitness or fatigue as a number",
        "Never invent events",
        "in English, even when the notes are in another language",
    ):
        assert rule in SYSTEM_INSTRUCTION


def test_check_review_accepts_and_trims() -> None:
    content = ReviewContent(
        script=f"  {LINE}\n",
        options=(ReviewOption(" Rest fully ", " Take a few days off. "), OPTIONS[1]),
    )

    checked = check_review(content)

    assert checked.script == LINE
    assert checked.options[0] == ReviewOption("Rest fully", "Take a few days off.")


@pytest.mark.parametrize(("count", "ok"), [(27, False), (28, True), (40, True), (41, False)])
def test_check_review_counts_words_of_the_line(count: int, ok: bool) -> None:
    content = ReviewContent(script=" ".join(["word"] * count), options=OPTIONS)

    if ok:
        check_review(content)
    else:
        with pytest.raises(InvalidReviewError):
            check_review(content)


@pytest.mark.parametrize("count", [0, 1, 4])
def test_check_review_needs_two_or_three_options(count: int) -> None:
    options = tuple(ReviewOption(f"Option {i}", "One short sentence.") for i in range(count))

    with pytest.raises(InvalidReviewError):
        check_review(ReviewContent(script=LINE, options=options))


@pytest.mark.parametrize(
    "option",
    [
        pytest.param(ReviewOption("  ", "One short sentence."), id="blank_label"),
        pytest.param(ReviewOption("x" * 65, "One short sentence."), id="label_too_long"),
        pytest.param(ReviewOption("Go easy", ""), id="blank_description"),
        pytest.param(ReviewOption("Go easy", "x" * 256), id="description_too_long"),
    ],
)
def test_check_review_fits_options_into_the_columns(option: ReviewOption) -> None:
    with pytest.raises(InvalidReviewError):
        check_review(ReviewContent(script=LINE, options=(OPTIONS[0], option)))
