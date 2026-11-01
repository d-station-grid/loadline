"""Gemini の adapter の分岐。応答は本物の Gemini から記録したもの（tests/fixtures/）を使う。

記録は gemini-3.8-flash に、順調・疲労・走れなかった週の 3 つを書かせたもの。テストに
要らない思考の署名と HTTP ヘッダは除いてある。
"""

import asyncio
import json
from pathlib import Path

import httpx
import pytest
from google.genai import errors, types

from app.adapters.gemini import GeminiReviewWriter, gemini_writer
from app.core.config import Settings
from app.domain.fallback_review import ReviewOption

FIXTURES = Path(__file__).parent / "fixtures"
MODELS = ["model-a", "model-b"]


def recorded(name: str) -> types.GenerateContentResponse:
    text = (FIXTURES / f"gemini_review_{name}.json").read_text()
    return types.GenerateContentResponse.model_validate_json(text)


def response_with(text: str | None) -> types.GenerateContentResponse:
    return types.GenerateContentResponse(
        candidates=[
            types.Candidate(content=types.Content(role="model", parts=[types.Part(text=text)]))
        ]
    )


def busy() -> errors.ClientError:
    return errors.ClientError(
        429,
        {"error": {"code": 429, "message": "Resource exhausted", "status": "RESOURCE_EXHAUSTED"}},
    )


class FakeGenerate:
    """呼ばれた順に results を返す（例外なら投げる）。呼ばれたモデルを控える。"""

    def __init__(self, *results: types.GenerateContentResponse | Exception) -> None:
        self._results = list(results)
        self.models: list[str] = []
        self.configs: list[types.GenerateContentConfig] = []

    async def __call__(
        self, *, model: str, contents: str, config: types.GenerateContentConfig
    ) -> types.GenerateContentResponse:
        self.models.append(model)
        self.configs.append(config)
        result = self._results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def writer(generate: FakeGenerate, timeout_sec: float = 5.0) -> GeminiReviewWriter:
    return GeminiReviewWriter(generate, MODELS, timeout_sec)


@pytest.mark.parametrize("name", ["steady", "fatigued", "no_training"])
async def test_recorded_responses_become_reviews(name: str) -> None:
    """記録した本物の応答が、そのまま振り返りになる。"""
    response = recorded(name)
    generate = FakeGenerate(response)

    review = await writer(generate).write("prompt")

    assert review is not None
    expected = json.loads(response.text or "")
    assert review.script == expected["line"]
    assert review.options == tuple(
        ReviewOption(o["label"], o["description"]) for o in expected["options"]
    )
    assert generate.models == ["model-a"]


async def test_asks_for_json_in_the_review_schema() -> None:
    generate = FakeGenerate(recorded("steady"))

    await writer(generate).write("prompt")

    config = generate.configs[0]
    assert config.response_mime_type == "application/json"
    assert config.system_instruction is not None


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(busy(), id="busy_429"),
        pytest.param(errors.ServerError(503, {"error": {"code": 503}}), id="unavailable_503"),
        pytest.param(httpx.ConnectError("connection refused"), id="network"),
    ],
)
async def test_moves_to_the_next_model_when_a_model_fails(error: Exception) -> None:
    """混雑や障害では、同じモデルでやり直さず、控えのモデルへ。"""
    generate = FakeGenerate(error, recorded("steady"))

    review = await writer(generate).write("prompt")

    assert review is not None
    assert generate.models == ["model-a", "model-b"]


async def test_retries_the_same_model_once_when_json_is_broken() -> None:
    """途中で切れた JSON は、同じモデルでもう 1 回だけ。"""
    text = recorded("fatigued").text or ""
    generate = FakeGenerate(response_with(text[: len(text) // 2]), recorded("fatigued"))

    review = await writer(generate).write("prompt")

    assert review is not None
    assert generate.models == ["model-a", "model-a"]


async def test_moves_on_after_two_responses_that_break_the_rules() -> None:
    """長さの決まりに合わない応答が 2 回続いたら、次のモデルへ。"""
    too_short = response_with(json.dumps({"line": "Rest.", "options": []}))
    generate = FakeGenerate(too_short, response_with(None), recorded("no_training"))

    review = await writer(generate).write("prompt")

    assert review is not None
    assert generate.models == ["model-a", "model-a", "model-b"]


async def test_returns_none_when_every_model_fails() -> None:
    """どのモデルでもだめなら None。呼ぶ側が定型に切り替える。"""
    generate = FakeGenerate(busy(), busy())

    assert await writer(generate).write("prompt") is None
    assert generate.models == MODELS


async def test_returns_none_when_it_takes_too_long() -> None:
    class Slow(FakeGenerate):
        async def __call__(
            self, *, model: str, contents: str, config: types.GenerateContentConfig
        ) -> types.GenerateContentResponse:
            await asyncio.sleep(1)
            return recorded("steady")

    assert await writer(Slow(), timeout_sec=0.01).write("prompt") is None


async def test_other_errors_are_not_hidden() -> None:
    """呼び方の誤りなど、想定していない例外は定型で隠さず、そのまま上げる。"""
    generate = FakeGenerate(TypeError("bad argument"))

    with pytest.raises(TypeError):
        await writer(generate).write("prompt")


def test_needs_at_least_one_model() -> None:
    with pytest.raises(ValueError):
        GeminiReviewWriter(FakeGenerate(), [], 5.0)


def test_settings_without_a_project_do_not_call_gemini() -> None:
    assert gemini_writer(Settings(gemini_project="")) is None
    assert isinstance(gemini_writer(Settings(gemini_project="test-project")), GeminiReviewWriter)
