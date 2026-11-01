"""Vertex AI の Gemini に、振り返りのセリフと選択肢を書いてもらう。

構造化出力で JSON を受け取り、domain の決まり（長さと数）で確かめる。モデルは先頭から
順に試す。混雑などで呼べなければ次のモデルへ、壊れた JSON や決まりに合わない応答なら
同じモデルでもう 1 回だけやり直す。全体で timeout_sec を超えるか、どのモデルでも
だめなら None を返し、呼ぶ側が定型に切り替える。
"""

import asyncio
import logging
from collections.abc import Sequence
from typing import Protocol

import httpx
from google import genai
from google.auth.exceptions import GoogleAuthError
from google.genai import errors, types
from pydantic import BaseModel, Field, ValidationError

from app.core.config import Settings
from app.domain.fallback_review import ReviewContent, ReviewOption
from app.domain.review_prompt import SYSTEM_INSTRUCTION, InvalidReviewError, check_review

logger = logging.getLogger(__name__)

# 1 つのモデルで試す回数。2 回目は、壊れた JSON や決まりに合わない応答のやり直し
ATTEMPTS_PER_MODEL = 2


class _Option(BaseModel):
    label: str = Field(description="Button text, 2 to 4 words.")
    description: str = Field(
        description="One short sentence shown under the button, at most 14 words. Not spoken."
    )


class _Review(BaseModel):
    line: str = Field(description="What you say aloud, 28 to 40 words.")
    options: list[_Option] = Field(description="Two or three options. One must be the gentle one.")


_CONFIG = types.GenerateContentConfig(
    system_instruction=SYSTEM_INSTRUCTION,
    response_mime_type="application/json",
    response_schema=_Review,
    temperature=0.8,
    # 考える過程のトークンも含まれる。小さいと JSON が途中で切れる
    max_output_tokens=8000,
)


class GenerateContent(Protocol):
    """client.aio.models.generate_content の形。テストでは記録した応答を返す関数に替える。"""

    async def __call__(
        self, *, model: str, contents: str, config: types.GenerateContentConfig
    ) -> types.GenerateContentResponse: ...


class GeminiReviewWriter:
    def __init__(
        self, generate: GenerateContent, models: Sequence[str], timeout_sec: float
    ) -> None:
        if not models:
            raise ValueError("at least one model is required")
        self._generate = generate
        self._models = tuple(models)
        self._timeout_sec = timeout_sec

    async def write(self, contents: str) -> ReviewContent | None:
        """contents（domain の review_prompt）から振り返りを書く。書けなければ None。"""
        try:
            async with asyncio.timeout(self._timeout_sec):
                return await self._try_models(contents)
        except TimeoutError:
            logger.warning("gemini: gave up after %s seconds", self._timeout_sec)
            return None

    async def _try_models(self, contents: str) -> ReviewContent | None:
        for model in self._models:
            for attempt in range(1, ATTEMPTS_PER_MODEL + 1):
                try:
                    response = await self._generate(model=model, contents=contents, config=_CONFIG)
                except (errors.APIError, httpx.HTTPError, GoogleAuthError) as error:
                    # 混雑（429）や障害は、同じモデルでやり直さず次のモデルへ
                    logger.warning("gemini: %s failed: %r", model, error)
                    break
                try:
                    return _parse(response)
                except (ValidationError, InvalidReviewError) as error:
                    logger.warning("gemini: %s attempt %d invalid: %s", model, attempt, error)
        return None


def _parse(response: types.GenerateContentResponse) -> ReviewContent:
    """応答の JSON を読み、決まりに合うか確かめる。途中で切れた JSON は ValidationError。"""
    text = response.text
    if not text:
        # 安全のための打ち切りなどで、本文が空のことがある
        raise InvalidReviewError("empty response")
    review = _Review.model_validate_json(text)
    return check_review(
        ReviewContent(
            script=review.line,
            options=tuple(ReviewOption(o.label, o.description) for o in review.options),
        )
    )


def gemini_writer(settings: Settings) -> GeminiReviewWriter | None:
    """設定から作る。プロジェクトが空なら None（呼ばずに定型にする）。

    認証は呼ぶときに Application Default Credentials で行う。本番は Cloud Run の
    サービスアカウント、手元は gcloud auth application-default login。
    """
    if not settings.gemini_project:
        return None
    client = genai.Client(
        vertexai=True, project=settings.gemini_project, location=settings.gemini_location
    )
    return GeminiReviewWriter(
        client.aio.models.generate_content, settings.gemini_models, settings.gemini_timeout_sec
    )
