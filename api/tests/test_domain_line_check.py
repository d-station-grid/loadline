import pytest

from app.domain.fallback_review import ReviewContent, ReviewOption
from app.domain.line_check import YES_CUTOFF, LineCheck, flagged, text_to_check


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
    assert flagged(LineCheck(pushes_harder=yes, medical_advice=0.0)) == (
        {"pushes_harder": yes} if is_flagged else {}
    )
    assert flagged(LineCheck(pushes_harder=0.0, medical_advice=yes)) == (
        {"medical_advice": yes} if is_flagged else {}
    )


def test_both_can_be_flagged() -> None:
    assert flagged(LineCheck(pushes_harder=0.5, medical_advice=0.9)) == {
        "pushes_harder": 0.5,
        "medical_advice": 0.9,
    }


def test_text_to_check_includes_the_options() -> None:
    content = ReviewContent(
        script="Nice week.",
        options=(ReviewOption("Rest", "Take a day off."), ReviewOption("Go", "Ride more.")),
    )

    assert text_to_check(content) == "Nice week. Rest: Take a day off. Go: Ride more."
