import pytest

from app.domain.expression import (
    CONFIDENCE_CUTOFF,
    DEFAULT_EXPRESSION,
    Expression,
    ExpressionAnswer,
    expression_for,
)


@pytest.mark.parametrize("name", [e.value for e in Expression])
def test_a_confident_answer_is_used(name: str) -> None:
    assert expression_for(ExpressionAnswer(name, 0.9)) == Expression(name)


@pytest.mark.parametrize(
    "answer",
    [
        pytest.param(None, id="no_answer"),
        pytest.param(ExpressionAnswer("happy", 0.59), id="just_below_the_cutoff"),
        pytest.param(ExpressionAnswer("happy", float("nan")), id="nan"),
        pytest.param(ExpressionAnswer("angry", 0.99), id="not_one_of_ours"),
        pytest.param(ExpressionAnswer("Happy", 0.99), id="different_case"),
    ],
)
def test_otherwise_the_avatar_stays_relaxed(answer: ExpressionAnswer | None) -> None:
    """確信度が低い、答えがない、知らない名前なら relaxed に倒す。"""
    assert DEFAULT_EXPRESSION == Expression.RELAXED
    assert expression_for(answer) == Expression.RELAXED


def test_the_cutoff_itself_is_confident_enough() -> None:
    assert CONFIDENCE_CUTOFF == 0.6
    assert expression_for(ExpressionAnswer("sad", 0.6)) == Expression.SAD
