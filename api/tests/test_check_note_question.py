"""メモの問いの期待値を確かめるスクリプト。本物の Jev は呼ばない。"""

from scripts.check_note_question import CASES, Case, render, run
from tests.test_jev_adapter import FakeSystemOne, answered, checker


def test_cases_cover_both_answers_in_english_and_japanese() -> None:
    """立てる例と立てない例が、英語と日本語の両方にある。治った例と筋肉痛の例も入れる。"""
    bodies = {c.body: c.flag for c in CASES}

    for flag in (True, False):
        assert any(f is flag and b.isascii() for b, f in bodies.items())
        assert any(f is flag and not b.isascii() for b, f in bodies.items())
    assert bodies["膝はもう大丈夫。"] is False
    assert bodies["筋肉痛。"] is False


async def test_run_asks_one_note_at_a_time_and_compares_with_the_cutoff() -> None:
    system_one = FakeSystemOne(answered(mentions_health=0.4))
    cases = (Case("Knee hurts.", True), Case("Legs heavy.", False))

    results = await run(checker(system_one), cases)

    assert system_one.states == [
        {"notes": "2026-10-12 Knee hurts."},
        {"notes": "2026-10-12 Legs heavy."},
    ]
    assert [r.ok for r in results] == [True, False]
    assert render(results).splitlines()[2:] == [
        "| Knee hurts. | 立てる | 0.40 | ✓ |",
        "| Legs heavy. | 立てない | 0.40 | ✗ |",
    ]


async def test_a_note_that_cannot_be_checked_does_not_pass() -> None:
    results = await run(checker(FakeSystemOne(answered())), (Case("Knee hurts.", True),))

    assert not results[0].ok
    assert "確かめられない" in render(results)
