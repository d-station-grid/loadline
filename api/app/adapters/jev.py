"""TypeSafe AI の Jev に、LLM が書いたセリフを話してよいか、その週のメモが痛みや病気に
触れているかを確かめてもらう。

セリフは 1 回の呼び出しで、無理強い、医療の助言、増やすことを勧めているかの 3 つを Noul
（はい・いいえの確率）で、セリフに合う表情を Choice で聞く。
メモは別の 1 回で、痛みや病気に触れているかを聞く。セリフより先に、LLM に書かせる前に聞く。
話してよいか、体調のフラグを立てるか（境目との比較）は domain の line_check と note_check で
行う。ここは聞いて、答えを LineCheck と NoteCheck に写すだけ。

失敗、時間切れ、想定外の応答では None を返し、呼ぶ側が定型に切り替える。やり直しはしない。
待つのは 1 回で、SDK のやり直しも切る。
"""

import asyncio
import logging
import math
from collections.abc import Mapping, Sequence
from typing import Protocol

from typesafe_sdk import (
    AsyncTypeSafeClient,
    Choice,
    Content,
    Noul,
    Question,
    RetryPolicy,
    SystemOneResponse,
    TypeSafeAuthenticationError,
    TypeSafeBadRequestError,
    TypeSafeError,
    TypeSafeNotFoundError,
    TypeSafePermissionDeniedError,
    TypeSafeUnprocessableEntityError,
)

from app.core.config import Settings
from app.domain.expression import ExpressionAnswer
from app.domain.fallback_review import ReviewContent
from app.domain.line_check import LineCheck, text_to_check
from app.domain.note_check import NoteCheck, notes_to_check
from app.domain.review_prompt import NoteForReview

logger = logging.getLogger(__name__)

# 呼び直しても同じになる、こちらの誤り。キー（401）、権限（403）、モデル名（404）、
# リクエストの形（400、422）。気づけるように error で残す
_OUR_MISTAKES = (
    TypeSafeAuthenticationError,
    TypeSafePermissionDeniedError,
    TypeSafeNotFoundError,
    TypeSafeBadRequestError,
    TypeSafeUnprocessableEntityError,
)

# pushes_harder と medical_advice は、試作で危ないセリフをすべて止められた言い方のまま。
# offers_more と expression は 3 本目で足した。変えたら scripts/check_line_questions.py で
# 本物の Jev に聞き、期待どおりか確かめる。4 つとも同じ 1 回の呼び出しで聞く
QUESTIONS: dict[str, Question] = {
    "pushes_harder": Noul(
        instructions=(
            "`line` pressures the listener: it orders or shames them into training, "
            "tells them to keep training despite tiredness, soreness or pain, "
            "or tells them to make up for missed training. "
            "A gentle, optional suggestion that the listener is free to decline does not count, "
            "even if it suggests a harder session."
        ),
    ),
    "medical_advice": Noul(
        instructions=(
            "`line` gives a medical diagnosis, names a medicine or a treatment to take, "
            "or says that a symptom is nothing to worry about. "
            "Simply suggesting rest or suggesting to see a doctor does not count."
        ),
    ),
    # 増やす選択肢を出してはいけない週だけで使う。pushes_harder が通す、押し付けない提案も拾う
    "offers_more": Noul(
        instructions=(
            "`line` suggests or invites the listener to train more than before: more sessions, "
            "longer sessions, harder sessions or higher intensity. "
            "It counts even if the suggestion is gentle and optional. "
            "Keeping the same amount, going easier, resting, or one short easy session to get "
            "moving again after time off does not count."
        ),
    ),
    # relaxed は表情が決まらないときの顔でもあるので、説明を狭くして寄りすぎないようにする。
    # ほめる、祝う文は、軽く過ごす提案が入っていても happy
    "expression": Choice(
        instructions="Which facial expression fits an avatar saying `line` aloud?",
        criteria={
            "happy": "Cheerful: it praises or celebrates something the listener did, such as "
            "a good week, a personal best or coming back after a break. Choose this even if "
            "it also suggests keeping things easy.",
            "relaxed": "Calm: it is mostly about resting, recovering or a quiet, ordinary week, "
            "and it does not praise or celebrate anything.",
            "sad": "Sympathetic: it acknowledges something hard, such as pain, sickness "
            "or being unable to train.",
            "surprised": "Amazed: it reacts to something unexpected or remarkable, such as "
            "a sudden big jump in training.",
        },
    ),
}


# メモの問い。変えたら scripts/check_note_question.py で本物の Jev に聞き、期待どおりか確かめる。
# 立てるのは、今ある痛み、けが、病気、体の不調（良くなってきた、治療中を含む）。
# 立てないのは、治ったと書いてあるもの、練習の後の普通の筋肉痛や張り、疲れ、寝不足、脚の重さ。
# これらで立てると、ほとんどの週で増やす選択肢が消えるため
NOTE_QUESTIONS: dict[str, Question] = {
    "mentions_health": Noul(
        instructions=(
            "`notes` say the writer has pain, an injury, an illness or another health problem "
            "now, such as knee pain, back pain, a cold, a fever or feeling sick. "
            "It still counts if the note says it is getting better or is being treated. "
            "It does not count if the note says the problem is gone. "
            "Ordinary muscle soreness or stiffness after training, being tired, sleeping badly "
            "or having heavy legs does not count by itself."
        ),
    ),
}


class InvalidAnswerError(Exception):
    """Jev の応答に、聞いた問いの答えがないか、確率が 0〜1 の数でない。"""


class SystemOne(Protocol):
    """AsyncTypeSafeClient.system_one の形。テストでは決めた応答を返す関数に替える。"""

    async def __call__(
        self, state: Content, questions: Mapping[str, Question]
    ) -> SystemOneResponse: ...


class JevLineChecker:
    def __init__(
        self,
        system_one: SystemOne,
        timeout_sec: float,
        client: AsyncTypeSafeClient | None = None,
    ) -> None:
        """client は system_one の持ち主。片付けられないように一緒に持つ（gemini と同じ）。"""
        self._system_one = system_one
        self._client = client
        self._timeout_sec = timeout_sec

    async def check(self, content: ReviewContent) -> LineCheck | None:
        """content を確かめた答え。確かめられなければ None。"""
        response = await self._ask({"line": text_to_check(content)}, QUESTIONS)
        if response is None:
            return None
        try:
            return _parse(response)
        except InvalidAnswerError as error:
            logger.warning("jev: unexpected answer: %s", error)
            return None

    async def check_notes(self, notes: Sequence[NoteForReview]) -> NoteCheck | None:
        """その週のメモを確かめた答え。確かめられなければ None。メモが空なら、呼ぶ側が呼ばない。"""
        response = await self._ask({"notes": notes_to_check(notes)}, NOTE_QUESTIONS)
        if response is None:
            return None
        try:
            return NoteCheck(mentions_health=_yes(response, "mentions_health"))
        except InvalidAnswerError as error:
            logger.warning("jev: unexpected answer about the notes: %s", error)
            return None

    async def _ask(
        self, state: Content, questions: Mapping[str, Question]
    ) -> SystemOneResponse | None:
        """1 回だけ聞く。失敗、時間切れでは None。文の中身はログに残さない。"""
        try:
            async with asyncio.timeout(self._timeout_sec):
                return await self._system_one(state, questions)
        except TimeoutError:
            # SDK の時間切れ（TypeSafeAPITimeoutError）も TimeoutError
            logger.warning("jev: gave up after %s seconds", self._timeout_sec)
            return None
        except _OUR_MISTAKES as error:
            logger.error("jev: rejected the request: %r", error)
            return None
        except TypeSafeError as error:
            # 混雑、障害、通信の失敗、壊れた応答（TypeSafeAPIResponseValidationError）
            logger.warning("jev: failed: %r", error)
            return None


def _yes(response: SystemOneResponse, name: str) -> float:
    answer = response.nouls.get(name)
    if answer is None:
        raise InvalidAnswerError(f"no answer for {name}")
    # NaN はどの比較も偽になり、境目を素通りするので、ここで止める
    if not (math.isfinite(answer.noul) and 0.0 <= answer.noul <= 1.0):
        raise InvalidAnswerError(f"{name} is not a probability: {answer.noul}")
    return answer.noul


def _parse(response: SystemOneResponse) -> LineCheck:
    return LineCheck(
        pushes_harder=_yes(response, "pushes_harder"),
        medical_advice=_yes(response, "medical_advice"),
        offers_more=_yes(response, "offers_more"),
        expression=_expression(response),
    )


def _expression(response: SystemOneResponse) -> ExpressionAnswer | None:
    """表情の答え。なければ None。名前と確信度は domain の expression_for で確かめる。

    表情が分からなくても、話してよいかの答えは使えるので、ここでは止めない。
    """
    answer = response.choices.get("expression")
    if answer is None:
        logger.warning("jev: no answer for expression")
        return None
    return ExpressionAnswer(choice=answer.choice, confidence=answer.confidence)


def jev_checker(settings: Settings) -> JevLineChecker | None:
    """設定から作る。キーが空なら None（確かめられないので、LLM の文は話さず定型にする）。

    キーの形が壊れている、時間切れの秒数が 0 以下などで作れないときも None にする。
    週次レビューを 500 にせず、定型で作れるようにするため。
    """
    if not settings.typesafe_api_key:
        return None
    try:
        client = AsyncTypeSafeClient(
            api_key=settings.typesafe_api_key,
            model=settings.typesafe_model,
            retry=RetryPolicy(max_retries=0),
            timeout=settings.typesafe_timeout_sec,
        )
    except TypeSafeError as error:
        logger.error("jev: could not create the client: %r", error)
        return None
    return JevLineChecker(client.system_one, settings.typesafe_timeout_sec, client=client)
