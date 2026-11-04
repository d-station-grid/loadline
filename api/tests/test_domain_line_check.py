import pytest

from app.domain.fallback_review import ReviewContent, ReviewOption
from app.domain.line_check import YES_CUTOFF, LineCheck, flagged, text_to_check


def check(pushes: float = 0.0, medical: float = 0.0, more: float = 0.0) -> LineCheck:
    return LineCheck(
        pushes_harder=pushes, medical_advice=medical, offers_more=more, expression=None
    )


@pytest.mark.parametrize(
    ("yes", "is_flagged"),
    [
        pytest.param(0.0, False, id="zero"),
        pytest.param(0.3499, False, id="just_below"),
        pytest.param(0.35, True, id="at_the_cutoff"),
        pytest.param(0.3501, True, id="just_above"),
        pytest.param(1.0, True, id="one"),
    ],
)
def test_cutoff(yes: float, is_flagged: bool) -> None:
    """境目ちょうどは「はい」に倒す。"""
    assert YES_CUTOFF == 0.35
    for may_offer_more in (True, False):
        assert flagged(check(pushes=yes), may_offer_more) == (
            {"pushes_harder": yes} if is_flagged else {}
        )
        assert flagged(check(medical=yes), may_offer_more) == (
            {"medical_advice": yes} if is_flagged else {}
        )
    assert flagged(check(more=yes), may_offer_more=False) == (
        {"offers_more": yes} if is_flagged else {}
    )


def test_both_can_be_flagged() -> None:
    assert flagged(check(pushes=0.5, medical=0.9), may_offer_more=True) == {
        "pushes_harder": 0.5,
        "medical_advice": 0.9,
    }


def test_offering_more_is_flagged_only_when_more_may_not_be_offered() -> None:
    """増やす選択肢を出してよい週（休めている、順調）は、増やすことを勧めても話してよい。"""
    assert flagged(check(more=0.9), may_offer_more=True) == {}
    assert flagged(check(more=0.9), may_offer_more=False) == {"offers_more": 0.9}


def test_text_to_check_includes_the_options() -> None:
    content = ReviewContent(
        script="Nice week.",
        options=(ReviewOption("Rest", "Take a day off."), ReviewOption("Go", "Ride more.")),
    )

    assert text_to_check(content) == "Nice week. Rest: Take a day off. Go: Ride more."
