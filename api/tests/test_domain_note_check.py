from datetime import date

import pytest

from app.domain.note_check import NoteCheck, health_flag, notes_to_check
from app.domain.review_prompt import NoteForReview


def test_notes_are_joined_by_date_one_per_line() -> None:
    """日付順に、日付、ラベル（あれば）、本文の順で 1 行ずつ。"""
    notes = [
        NoteForReview(date(2026, 10, 18), "Hills", "Long ride."),
        NoteForReview(date(2026, 10, 12), None, "Back pain again."),
    ]

    assert notes_to_check(notes) == "2026-10-12 Back pain again.\n2026-10-18 Hills Long ride."


@pytest.mark.parametrize(
    ("yes", "flag"),
    [(0.0, False), (0.349, False), (0.35, True), (1.0, True)],
)
def test_health_flag_uses_the_same_cutoff_as_the_line_check(yes: float, flag: bool) -> None:
    """0.5 より低い境目で、安全側（立てる側）に倒す。"""
    assert health_flag(NoteCheck(mentions_health=yes)) is flag
