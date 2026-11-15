"""Gemini の adapter の分岐。応答は本物の Gemini から記録したもの（tests/fixtures/）を使う。

記録は gemini-3.8-flash に、順調・疲労・走れなかった週の 3 つを書かせたもの。画面で読む
長めの文（detail）を足したときに、今の指示と出力の形で記録し直した。テストに要らない思考の
署名と HTTP ヘッダは除いてある。
"""

import asyncio
import gc
import json
from pathlib import Path

import httpx
import pytest
from google.auth.exceptions import DefaultCredentialsError
from google.genai import errors, types

from app.adapters.gemini import GeminiReviewWriter, _Review, _ReviewJa, gemini_writer
from app.core.config import Settings
from app.domain.fallback_review import ReviewOption
from app.domain.language import Language
from app.domain.review_prompt import SYSTEM_INSTRUCTION, system_instruction

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
    """記録した本物の応答が、そのまま週次レビューになる。"""
    response = recorded(name)
    generate = FakeGenerate(response)

    review = await writer(generate).write("prompt")

    assert review is not None
    expected = json.loads(response.text or "")
    assert review.script == expected["line"]
    assert review.detail == expected["detail"]
    assert review.options == tuple(
        ReviewOption(o["label"], o["description"]) for o in expected["options"]
    )
    assert generate.models == ["model-a"]


async def test_asks_for_json_in_the_review_schema() -> None:
    generate = FakeGenerate(recorded("steady"))

    await writer(generate).write("prompt")

    config = generate.configs[0]
    assert config.response_mime_type == "application/json"
    assert config.response_schema is _Review
    # detail を先に書かせ、line をその短い話し言葉にする
    assert list(_Review.model_json_schema()["properties"]) == ["detail", "line", "options"]
    assert config.system_instruction is not None


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(busy(), id="busy_429"),
        pytest.param(errors.ClientError(404, {"error": {"code": 404}}), id="no_such_model_404"),
        pytest.param(errors.ServerError(500, {"error": {"code": 500}}), id="internal_500"),
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


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(errors.ClientError(400, {"error": {"code": 400}}), id="bad_request_400"),
        pytest.param(errors.ClientError(401, {"error": {"code": 401}}), id="unauthenticated_401"),
        pytest.param(errors.ClientError(403, {"error": {"code": 403}}), id="forbidden_403"),
        # google-auth の例外には型が付いていない
        pytest.param(DefaultCredentialsError("no creds"), id="no_credentials"),  # type: ignore[no-untyped-call]
    ],
)
async def test_stops_at_once_when_another_model_would_fail_the_same_way(
    error: Exception, caplog: pytest.LogCaptureFixture
) -> None:
    """リクエストの誤り、権限、認証の失敗はモデルを替えても直らない。次へ進まず打ち切る。"""
    generate = FakeGenerate(error, recorded("steady"))

    assert await writer(generate).write("prompt") is None
    assert generate.models == ["model-a"]
    assert [r.levelname for r in caplog.records] == ["ERROR"]


async def test_retries_the_same_model_once_when_json_is_broken() -> None:
    """途中で切れた JSON は、同じモデルでもう 1 回だけ。"""
    text = recorded("fatigued").text or ""
    generate = FakeGenerate(response_with(text[: len(text) // 2]), recorded("fatigued"))

    review = await writer(generate).write("prompt")

    assert review is not None
    assert generate.models == ["model-a", "model-a"]


@pytest.mark.parametrize(
    "detail",
    [
        pytest.param("Too short.", id="too_few_words"),
        pytest.param("1 2 3 4 " + " ".join(["ride"] * 80), id="too_many_numbers"),
    ],
)
async def test_leaves_out_only_the_detail_when_it_breaks_the_rules(
    detail: str, caplog: pytest.LogCaptureFixture
) -> None:
    """長めの文が決まりに合わなくても、書き直させずにセリフと選択肢を使い、長めの文だけ落とす。
    ログには理由だけを残し、文言は残さない。"""
    data = json.loads(recorded("steady").text or "")
    generate = FakeGenerate(response_with(json.dumps({**data, "detail": detail})))

    review = await writer(generate).write("prompt")

    assert review is not None
    assert review.script == data["line"]
    assert review.detail is None
    assert generate.models == ["model-a"]
    assert "leaving out the detail" in caplog.text
    assert detail not in caplog.text


async def test_moves_on_after_two_responses_that_break_the_rules() -> None:
    """長さの決まりに合わない応答が 2 回続いたら、次のモデルへ。"""
    too_short = response_with(json.dumps({"detail": "Rest.", "line": "Rest.", "options": []}))
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


async def test_writer_keeps_the_client_open() -> None:
    """作った genai.Client が片付けられても、通信が閉じない。

    閉じると、本番の最初の呼び出しが「client has been closed」で失敗し、毎回定型になる。
    閉じたかどうかは SDK の中の httpx のクライアントで見る。
    """
    writer = gemini_writer(Settings(gemini_project="test-project"))
    assert writer is not None
    api_client = writer._generate.__self__._api_client  # type: ignore[attr-defined]

    gc.collect()
    await asyncio.sleep(0.05)  # 片付けのときに積まれる aclose を走らせる

    assert not api_client._async_httpx_client.is_closed


JAPANESE_REVIEW = {
    "detail": "今週は安定したリズムで練習できました。" * 12,
    "line": "いいリズムで練習が続いていますね。体力と疲労のバランスもとれています。"
    "このまま続けることが、体力を積み上げる近道ですよ。",
    "options": [
        {"label": "このリズムで", "description": "先週と同じように練習する。"},
        {"label": "少し軽めに", "description": "数日は軽めの練習にする。"},
    ],
}


async def test_writes_in_japanese_with_the_japanese_schema() -> None:
    """日本語では、日本語の指示と、長さを文字数で書いた形で頼み、文字数で確かめる。"""
    generate = FakeGenerate(response_with(json.dumps(JAPANESE_REVIEW, ensure_ascii=False)))

    review = await writer(generate).write("prompt", Language.JA)

    config = generate.configs[0]
    assert config.response_schema is _ReviewJa
    assert config.system_instruction == system_instruction(Language.JA)
    assert review is not None
    assert review.script == JAPANESE_REVIEW["line"]
    assert review.detail == JAPANESE_REVIEW["detail"]
    assert review.options[0] == ReviewOption("このリズムで", "先週と同じように練習する。")


async def test_english_is_the_default() -> None:
    generate = FakeGenerate(recorded("steady"))

    await writer(generate).write("prompt")

    assert generate.configs[0].system_instruction == SYSTEM_INSTRUCTION
