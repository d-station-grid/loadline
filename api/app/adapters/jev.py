"""TypeSafe AI の Jev に、LLM が書いたセリフを話してよいか確かめてもらう。

1 回の呼び出しで、無理強いと医療の助言の 2 つを Noul（はい・いいえの確率）で聞く。
話してよいかの判定（境目との比較）は domain の line_check で行う。ここは聞いて、答えを
LineCheck に写すだけ。

失敗、時間切れ、想定外の応答では None を返し、呼ぶ側が定型に切り替える。やり直しはしない。
待つのは 1 回で、SDK のやり直しも切る。
"""

import asyncio
import logging
import math
from collections.abc import Mapping
from typing import Protocol

from typesafe_sdk import (
    AsyncTypeSafeClient,
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
from app.domain.fallback_review import ReviewContent
from app.domain.line_check import LineCheck, text_to_check

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

# 問いは試作で危ないセリフをすべて止められた言い方のまま。変えるときは試作で確かめ直す。
# 表情などの問いも、ここに足せば同じ 1 回の呼び出しで聞ける
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
        try:
            async with asyncio.timeout(self._timeout_sec):
                response = await self._system_one({"line": text_to_check(content)}, QUESTIONS)
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
        try:
            return _parse(response)
        except InvalidAnswerError as error:
            logger.warning("jev: unexpected answer: %s", error)
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
    )


def jev_checker(settings: Settings) -> JevLineChecker | None:
    """設定から作る。キーが空なら None（確かめられないので、LLM の文は話さず定型にする）。

    キーの形が壊れている、時間切れの秒数が 0 以下などで作れないときも None にする。
    振り返りを 500 にせず、定型で作れるようにするため。
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
