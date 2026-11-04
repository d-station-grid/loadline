"""セリフの問いの期待値を確かめるスクリプト。本物の Jev は呼ばない。"""

from app.domain.expression import Expression
from scripts.check_line_questions import (
    BASELINE_QUESTIONS,
    CASES,
    Case,
    baseline,
    render,
    render_baseline,
    run,
)
from tests.test_jev_adapter import FakeSystemOne, answered, checker, line_answer


def test_cases_cover_both_answers_and_every_expression() -> None:
    assert {c.offers_more for c in CASES} == {True, False}
    assert set().union(*(c.expressions for c in CASES)) == set(Expression)


async def test_run_checks_offers_more_and_the_expression() -> None:
    case = Case(
        "Add a ride.", (("Add one", "One more ride."),), True, frozenset({Expression.HAPPY})
    )

    ok = await run(
        checker(FakeSystemOne(line_answer(offers_more=0.9, expression=("happy", 0.8)))), (case,)
    )
    unsure = await run(
        checker(FakeSystemOne(line_answer(offers_more=0.9, expression=("happy", 0.3)))), (case,)
    )
    missed = await run(
        checker(FakeSystemOne(line_answer(offers_more=0.1, expression=("happy", 0.8)))), (case,)
    )

    assert ok[0].ok
    # 確信度が低いと relaxed になり、期待の happy と合わない
    assert not unsure[0].ok
    assert not missed[0].ok
    assert render(ok).splitlines()[2] == (
        "| Add a ride. | 勧める | 0.90 | happy | happy (happy 0.80) | 0.00 / 0.00 | ✓ |"
    )


async def test_a_line_that_cannot_be_checked_does_not_pass() -> None:
    case = CASES[0]

    results = await run(checker(FakeSystemOne(line_answer(medical_advice=float("nan")))), (case,))

    assert not results[0].ok
    assert "確かめられない" in render(results)


async def test_baseline_asks_only_the_two_original_questions() -> None:
    """--baseline は試作の 2 つの問いだけで聞き、4 つまとめた値と並べる。"""
    case = CASES[0]
    two = FakeSystemOne(answered(pushes_harder=0.1, medical_advice=0.05))
    four = await run(checker(FakeSystemOne(line_answer(pushes_harder=0.4))), (case,))

    rows = await baseline(two, (case,))

    assert two.questions == [BASELINE_QUESTIONS]
    assert set(BASELINE_QUESTIONS) == {"pushes_harder", "medical_advice"}
    assert render_baseline(rows, four).splitlines()[2] == (
        f"| {case.script} | 0.10 | 0.40 | 0.05 | 0.00 |"
    )
