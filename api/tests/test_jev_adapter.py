"""Jev の adapter の分岐。本物の Jev は呼ばず、SDK の応答の型で作った値を返す偽物を使う。"""

import asyncio
import gc
from collections.abc import Mapping
from datetime import date
from typing import Any

import httpx2
import pytest
from typesafe_sdk import (
    ChoiceAnswer,
    Content,
    NoulAnswer,
    Question,
    SystemOneResponse,
    TypeSafeAPIConnectionError,
    TypeSafeAPIError,
    TypeSafeAPIResponseValidationError,
    TypeSafeAPITimeoutError,
    TypeSafeAuthenticationError,
    TypeSafeBadRequestError,
    TypeSafeInternalServerError,
    TypeSafeNotFoundError,
    TypeSafePermissionDeniedError,
    TypeSafeRateLimitError,
    TypeSafeUnprocessableEntityError,
    Usage,
)

from app.adapters.jev import NOTE_QUESTIONS, QUESTIONS, JevLineChecker, jev_checker
from app.core.config import Settings
from app.domain.expression import ExpressionAnswer
from app.domain.fallback_review import ReviewContent, ReviewOption
from app.domain.line_check import LineCheck, flagged
from app.domain.note_check import NoteCheck, health_flag
from app.domain.review_prompt import NoteForReview

CONTENT = ReviewContent(
    script="A calm week of riding.",
    options=(
        ReviewOption("Rest fully", "Take a few days off."),
        ReviewOption("Keep it steady", "Train the same way as last week."),
    ),
)


def answered(*, expression: tuple[str, float] | None = None, **nouls: float) -> SystemOneResponse:
    """Noul の答えと、あれば表情（Choice）の答え。表情は (名前, 確信度)。"""
    answers: dict[str, Any] = {name: NoulAnswer(noul=p) for name, p in nouls.items()}
    if expression is not None:
        name, confidence = expression
        answers["expression"] = ChoiceAnswer(
            choice=name, confidence=confidence, probabilities={name: confidence}
        )
    return SystemOneResponse(
        model="jev-latest", usage=Usage(input_tokens=120, output_tokens=4), answers=answers
    )


def line_answer(
    pushes_harder: float = 0.0,
    medical_advice: float = 0.0,
    offers_more: float = 0.0,
    expression: tuple[str, float] | None = ("relaxed", 0.9),
) -> SystemOneResponse:
    """セリフの確認への答え。3 つの Noul と表情。"""
    return answered(
        pushes_harder=pushes_harder,
        medical_advice=medical_advice,
        offers_more=offers_more,
        expression=expression,
    )


class FakeSystemOne:
    """決めた応答を返す（例外なら投げる）。受け取った state と問いを控える。"""

    def __init__(self, result: SystemOneResponse | Exception) -> None:
        self._result = result
        self.states: list[Content] = []
        self.questions: list[Mapping[str, Question]] = []

    async def __call__(
        self, state: Content, questions: Mapping[str, Question]
    ) -> SystemOneResponse:
        self.states.append(state)
        self.questions.append(questions)
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


def checker(system_one: FakeSystemOne, timeout_sec: float = 5.0) -> JevLineChecker:
    return JevLineChecker(system_one, timeout_sec)


def api_error(cls: type[TypeSafeAPIError], status: int) -> Exception:
    return cls(status, {"error": {"message": "no"}}, httpx2.Headers())


async def test_safe_answer() -> None:
    system_one = FakeSystemOne(line_answer(0.02, 0.01, 0.03, ("happy", 0.8)))

    check = await checker(system_one).check(CONTENT)

    assert check == LineCheck(
        pushes_harder=0.02,
        medical_advice=0.01,
        offers_more=0.03,
        expression=ExpressionAnswer("happy", 0.8),
    )
    assert flagged(check, may_offer_more=False) == {}


async def test_a_missing_expression_does_not_stop_the_check(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """表情の答えがなくても、話してよいかの答えは使う。表情は domain で relaxed にする。"""
    check = await checker(FakeSystemOne(line_answer(expression=None))).check(CONTENT)

    assert check is not None
    assert check.expression is None
    assert [r.levelname for r in caplog.records] == ["WARNING"]


async def test_asks_every_question_about_the_line_and_the_options_at_once() -> None:
    """話す部分と選択肢の文をつないだものを、4 つの問いで 1 回だけ聞く。"""
    system_one = FakeSystemOne(line_answer())

    await checker(system_one).check(CONTENT)

    assert system_one.states == [
        {
            "line": "A calm week of riding. Rest fully: Take a few days off. "
            "Keep it steady: Train the same way as last week."
        }
    ]
    assert system_one.questions == [QUESTIONS]
    assert set(QUESTIONS) == {"pushes_harder", "medical_advice", "offers_more", "expression"}


@pytest.mark.parametrize(
    ("pushes", "medical", "risks"),
    [
        pytest.param(0.9, 0.0, {"pushes_harder": 0.9}, id="pushes_harder"),
        pytest.param(0.0, 0.6, {"medical_advice": 0.6}, id="medical_advice"),
        pytest.param(0.35, 0.0, {"pushes_harder": 0.35}, id="exactly_at_the_cutoff"),
        pytest.param(0.4, 0.35, {"pushes_harder": 0.4, "medical_advice": 0.35}, id="both"),
    ],
)
async def test_answers_at_or_above_the_cutoff_are_flagged(
    pushes: float, medical: float, risks: dict[str, float]
) -> None:
    system_one = FakeSystemOne(line_answer(pushes, medical))

    check = await checker(system_one).check(CONTENT)

    assert check is not None
    assert flagged(check, may_offer_more=True) == risks


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(api_error(TypeSafeRateLimitError, 429), id="busy_429"),
        pytest.param(api_error(TypeSafeInternalServerError, 503), id="unavailable_503"),
        pytest.param(TypeSafeAPIConnectionError("connection refused"), id="network"),
        pytest.param(
            TypeSafeAPIResponseValidationError(200, {}, httpx2.Headers(), "answers"),
            id="broken_body",
        ),
    ],
)
async def test_returns_none_when_jev_fails(
    error: Exception, caplog: pytest.LogCaptureFixture
) -> None:
    assert await checker(FakeSystemOne(error)).check(CONTENT) is None
    assert [r.levelname for r in caplog.records] == ["WARNING"]


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(api_error(TypeSafeAuthenticationError, 401), id="unauthenticated_401"),
        pytest.param(api_error(TypeSafePermissionDeniedError, 403), id="forbidden_403"),
        pytest.param(api_error(TypeSafeNotFoundError, 404), id="no_such_model_404"),
        pytest.param(api_error(TypeSafeBadRequestError, 400), id="bad_request_400"),
        pytest.param(api_error(TypeSafeUnprocessableEntityError, 422), id="unprocessable_422"),
    ],
)
async def test_our_mistakes_are_logged_as_errors(
    error: Exception, caplog: pytest.LogCaptureFixture
) -> None:
    """キー、権限、モデル名、リクエストの誤りは呼び直しても直らない。error で残す。"""
    assert await checker(FakeSystemOne(error)).check(CONTENT) is None
    assert [r.levelname for r in caplog.records] == ["ERROR"]


async def test_returns_none_when_it_takes_too_long(caplog: pytest.LogCaptureFixture) -> None:
    class Slow(FakeSystemOne):
        async def __call__(
            self, state: Content, questions: Mapping[str, Question]
        ) -> SystemOneResponse:
            await asyncio.sleep(1)
            return line_answer()

    slow = Slow(line_answer())

    assert await checker(slow, timeout_sec=0.01).check(CONTENT) is None
    assert [r.levelname for r in caplog.records] == ["WARNING"]


async def test_returns_none_when_the_sdk_times_out() -> None:
    error = TypeSafeAPITimeoutError(15.0)

    assert await checker(FakeSystemOne(error)).check(CONTENT) is None


@pytest.mark.parametrize(
    "response",
    [
        pytest.param(answered(pushes_harder=0.0), id="missing_answer"),
        pytest.param(answered(pushes_harder=0.0, medical_advice=0.0), id="missing_offers_more"),
        pytest.param(answered(), id="no_answers"),
        pytest.param(line_answer(medical_advice=1.5), id="above_one"),
        pytest.param(line_answer(pushes_harder=-0.1), id="below_zero"),
        pytest.param(line_answer(offers_more=float("nan")), id="nan"),
    ],
)
async def test_returns_none_for_an_unexpected_answer(
    response: SystemOneResponse, caplog: pytest.LogCaptureFixture
) -> None:
    """聞いた問いの答えがない、確率でない応答は、確かめられなかったものとする。"""
    assert await checker(FakeSystemOne(response)).check(CONTENT) is None
    assert [r.levelname for r in caplog.records] == ["WARNING"]


async def test_other_errors_are_not_hidden() -> None:
    """呼び方の誤りなど、想定していない例外は定型で隠さず、そのまま上げる（gemini と同じ）。"""
    with pytest.raises(TypeError):
        await checker(FakeSystemOne(TypeError("bad argument"))).check(CONTENT)


def test_settings_without_a_key_do_not_call_jev() -> None:
    assert jev_checker(Settings(typesafe_api_key="")) is None
    assert isinstance(jev_checker(Settings(typesafe_api_key="test-key")), JevLineChecker)


@pytest.mark.parametrize(
    "fields",
    [
        pytest.param({"typesafe_api_key": "bad key"}, id="key_with_a_space"),
        pytest.param({"typesafe_api_key": "kéy"}, id="non_ascii_key"),
        pytest.param(
            {"typesafe_api_key": "test-key", "typesafe_timeout_sec": 0}, id="zero_timeout"
        ),
    ],
)
def test_settings_that_the_sdk_rejects_fall_back_to_no_checker(
    fields: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    """作れない設定では 500 にせず、checker なし（定型）にする。"""
    assert jev_checker(Settings(**fields)) is None
    assert [r.levelname for r in caplog.records] == ["ERROR"]


async def test_checker_keeps_the_client_open() -> None:
    """作ったクライアントが片付けられても、通信が閉じない。"""
    jev = jev_checker(Settings(typesafe_api_key="test-key"))
    assert jev is not None
    http_client = jev._system_one.__self__._http_client  # type: ignore[attr-defined]

    gc.collect()
    await asyncio.sleep(0.05)

    assert not http_client.is_closed


NOTES = [
    NoteForReview(date(2026, 10, 14), None, "Knee hurts on stairs."),
    NoteForReview(date(2026, 10, 12), "Work", "Deadline week."),
]


async def test_asks_about_the_notes_of_the_week_at_once() -> None:
    """メモを日付順に 1 行ずつつなぎ、体調の問いだけを 1 回聞く。"""
    system_one = FakeSystemOne(answered(mentions_health=0.91))

    check = await checker(system_one).check_notes(NOTES)

    assert check == NoteCheck(mentions_health=0.91)
    assert system_one.states == [
        {"notes": "2026-10-12 Work Deadline week.\n2026-10-14 Knee hurts on stairs."}
    ]
    assert system_one.questions == [NOTE_QUESTIONS]
    assert set(NOTE_QUESTIONS) == {"mentions_health"}


@pytest.mark.parametrize(
    ("yes", "flag"),
    [
        pytest.param(0.02, False, id="no"),
        pytest.param(0.34, False, id="just_below_the_cutoff"),
        pytest.param(0.35, True, id="exactly_at_the_cutoff"),
        pytest.param(0.9, True, id="yes"),
    ],
)
async def test_health_flag_is_decided_by_the_cutoff(yes: float, flag: bool) -> None:
    check = await checker(FakeSystemOne(answered(mentions_health=yes))).check_notes(NOTES)

    assert check is not None
    assert health_flag(check) is flag


@pytest.mark.parametrize(
    "result",
    [
        pytest.param(api_error(TypeSafeRateLimitError, 429), id="busy_429"),
        pytest.param(TypeSafeAPITimeoutError(15.0), id="sdk_timeout"),
        pytest.param(answered(pushes_harder=0.0, medical_advice=0.0), id="answers_of_the_line"),
        pytest.param(answered(mentions_health=float("nan")), id="nan"),
        pytest.param(answered(mentions_health=1.2), id="above_one"),
    ],
)
async def test_notes_that_cannot_be_checked_return_none(
    result: SystemOneResponse | Exception, caplog: pytest.LogCaptureFixture
) -> None:
    """失敗、時間切れ、想定外の応答は、確かめられなかったものとする。メモの文はログに残さない。"""
    assert await checker(FakeSystemOne(result)).check_notes(NOTES) is None
    assert [r.levelname for r in caplog.records] == ["WARNING"]
    assert all("Knee" not in r.getMessage() for r in caplog.records)
