"""Google Cloud Text-to-Speech の adapter の分岐。"""

import asyncio
import base64
import json

import httpx
import pytest
from google.auth.exceptions import TransportError

from app.adapters.google_tts import (
    ATTEMPTS,
    PROMPT,
    RETRY_WAIT_SEC,
    SYNTHESIZE_URL,
    GoogleVoice,
    google_voice,
)
from app.core.config import Settings

MP3 = b"ID3\x04\x00\x00mp3"
LINE = "今週もいいリズムで練習できましたね。"


class FakeGoogle:
    """Cloud Text-to-Speech の代わり。answers を先頭から順に返す。受けたリクエストを控える。"""

    def __init__(self, *answers: int | Exception | dict[str, object]) -> None:
        self.answers = list(answers)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        if isinstance(answer, dict):
            return httpx.Response(200, json=answer)
        if answer == 200:
            return httpx.Response(200, json={"audioContent": base64.b64encode(MP3).decode()})
        return httpx.Response(answer, json={"error": {"message": "no"}})


class Sleeps:
    def __init__(self) -> None:
        self.waited: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.waited.append(seconds)


async def _token() -> str:
    return "access-token"


def _voice(google: FakeGoogle, sleeps: Sleeps, timeout_sec: float = 45.0) -> GoogleVoice:
    client = httpx.AsyncClient(transport=httpx.MockTransport(google))
    return GoogleVoice(
        "gemini-2.5-pro-tts", "Leda", _token, timeout_sec, client=client, sleep=sleeps
    )


async def test_speak_returns_the_mp3() -> None:
    google, sleeps = FakeGoogle(200), Sleeps()

    assert await _voice(google, sleeps).speak(LINE) == MP3

    (request,) = google.requests
    assert str(request.url) == SYNTHESIZE_URL
    assert request.headers["Authorization"] == "Bearer access-token"
    assert sleeps.waited == []


async def test_the_style_is_sent_apart_from_the_line() -> None:
    """口調の指示は prompt、セリフは text に分ける。指示を文に混ぜると読み上げてしまうため。"""
    google = FakeGoogle(200)

    await _voice(google, Sleeps()).speak(LINE)

    body = json.loads(google.requests[0].content)
    assert body["input"] == {"prompt": PROMPT, "text": LINE}
    assert body["voice"] == {
        "languageCode": "ja-JP",
        "name": "Leda",
        "modelName": "gemini-2.5-pro-tts",
    }
    assert body["audioConfig"] == {"audioEncoding": "MP3"}


@pytest.mark.parametrize("busy", [429, 503])
async def test_busy_is_tried_once_more(busy: int) -> None:
    google, sleeps = FakeGoogle(busy, 200), Sleeps()

    assert await _voice(google, sleeps).speak(LINE) == MP3
    assert sleeps.waited == [RETRY_WAIT_SEC]


async def test_network_failure_is_tried_again() -> None:
    google, sleeps = FakeGoogle(httpx.ConnectError("reset"), 200), Sleeps()

    assert await _voice(google, sleeps).speak(LINE) == MP3


async def test_gives_up_after_the_attempts() -> None:
    google, sleeps = FakeGoogle(*([429] * ATTEMPTS)), Sleeps()

    assert await _voice(google, sleeps).speak(LINE) is None
    assert len(google.requests) == ATTEMPTS == 2


@pytest.mark.parametrize("refused", [400, 403])
async def test_refusal_is_not_tried_again(refused: int) -> None:
    google, sleeps = FakeGoogle(refused), Sleeps()

    assert await _voice(google, sleeps).speak(LINE) is None
    assert len(google.requests) == 1


@pytest.mark.parametrize(
    "answer",
    [
        pytest.param({}, id="no_audio"),
        pytest.param({"audioContent": "not base64!"}, id="broken_audio"),
    ],
)
async def test_unexpected_answer_is_none(answer: dict[str, object]) -> None:
    assert await _voice(FakeGoogle(answer), Sleeps()).speak(LINE) is None


async def test_token_failure_is_none() -> None:
    async def fails() -> str:
        raise TransportError("no metadata server")  # type: ignore[no-untyped-call]

    google = FakeGoogle(200)
    client = httpx.AsyncClient(transport=httpx.MockTransport(google))
    voice = GoogleVoice("gemini-2.5-pro-tts", "Leda", fails, 45.0, client=client)

    assert await voice.speak(LINE) is None
    assert google.requests == []


async def test_gives_up_after_the_timeout() -> None:
    class Slow:
        async def __call__(self, seconds: float) -> None:
            await asyncio.sleep(1)

    voice = _voice(FakeGoogle(503, 200), Sleeps(), timeout_sec=0.01)
    voice._sleep = Slow()

    assert await voice.speak(LINE) is None


def test_no_model_means_no_japanese_voice() -> None:
    """手元とテストではモデルを空にして、費用のかかる呼び出しをしない。"""
    assert google_voice(Settings(google_tts_model="")) is None
    assert google_voice(Settings(google_tts_model="gemini-2.5-pro-tts")) is not None
