import asyncio
import json
import logging

import httpx
import pytest
from google.auth.exceptions import TransportError

from app.adapters.tts import ATTEMPTS, RETRY_WAITS_SEC, KokoroVoice, kokoro_voice
from app.core.config import Settings

URL = "https://tts.example.run.app"
WAV = b"RIFF....WAVEfmt "


class FakeTts:
    """tts の代わり。answers を先頭から順に返す。受けたリクエストを控える。"""

    def __init__(self, *answers: int | Exception) -> None:
        self.answers = list(answers)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        if answer == 200:
            return httpx.Response(200, content=WAV, headers={"content-type": "audio/wav"})
        return httpx.Response(answer)


class Sleeps:
    def __init__(self) -> None:
        self.waited: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.waited.append(seconds)


async def _token() -> str:
    return "id-token"


def _voice(tts: FakeTts, sleeps: Sleeps, timeout_sec: float = 45.0) -> KokoroVoice:
    client = httpx.AsyncClient(transport=httpx.MockTransport(tts))
    return KokoroVoice(URL, _token, timeout_sec, client=client, sleep=sleeps)


async def test_speak_returns_the_wav_with_an_id_token() -> None:
    tts, sleeps = FakeTts(200), Sleeps()

    wav = await _voice(tts, sleeps).speak("A steady week.")

    assert wav == WAV
    (request,) = tts.requests
    assert str(request.url) == f"{URL}/speak"
    assert request.headers["Authorization"] == "Bearer id-token"
    assert json.loads(request.content) == {"text": "A steady week."}
    assert sleeps.waited == []


@pytest.mark.parametrize("busy", [429, 503])
async def test_busy_tts_is_tried_again_after_a_wait(busy: int) -> None:
    # 2 台とも読んでいる最中なら 429。空きが出るのを待ってやり直す
    tts, sleeps = FakeTts(busy, busy, 200), Sleeps()

    wav = await _voice(tts, sleeps).speak("A steady week.")

    assert wav == WAV
    assert len(tts.requests) == 3
    assert sleeps.waited == list(RETRY_WAITS_SEC)


async def test_network_failure_is_tried_again() -> None:
    tts, sleeps = FakeTts(httpx.ConnectError("reset"), 200), Sleeps()

    assert await _voice(tts, sleeps).speak("A steady week.") == WAV
    assert len(tts.requests) == 2


async def test_gives_up_after_three_attempts(caplog: pytest.LogCaptureFixture) -> None:
    tts, sleeps = FakeTts(*([429] * ATTEMPTS)), Sleeps()

    with caplog.at_level(logging.WARNING):
        assert await _voice(tts, sleeps).speak("A steady week.") is None

    assert ATTEMPTS == 3
    assert len(tts.requests) == ATTEMPTS
    assert "gave up after 3 attempts" in caplog.text


@pytest.mark.parametrize("rejected", [401, 403, 422])
async def test_rejected_request_is_not_tried_again(rejected: int) -> None:
    # 権限や中身の誤りは、やり直しても変わらない
    tts, sleeps = FakeTts(rejected), Sleeps()

    assert await _voice(tts, sleeps).speak("A steady week.") is None
    assert len(tts.requests) == 1
    assert sleeps.waited == []


async def test_id_token_failure_gives_up() -> None:
    async def broken_token() -> str:
        raise TransportError("no metadata server")  # type: ignore[no-untyped-call]

    tts = FakeTts(200)
    client = httpx.AsyncClient(transport=httpx.MockTransport(tts))
    voice = KokoroVoice(URL, broken_token, 45.0, client=client, sleep=Sleeps())

    assert await voice.speak("A steady week.") is None
    assert tts.requests == []


async def test_gives_up_after_the_timeout() -> None:
    # 待ちのあいだに上限を超えたら、残りは試さずに音声なしにする
    async def slow_sleep(seconds: float) -> None:
        await asyncio.sleep(1)

    tts = FakeTts(429, 200)
    client = httpx.AsyncClient(transport=httpx.MockTransport(tts))
    voice = KokoroVoice(URL, _token, 0.05, client=client, sleep=slow_sleep)

    assert await voice.speak("A steady week.") is None
    assert len(tts.requests) == 1


def test_no_voice_without_the_url() -> None:
    assert kokoro_voice(Settings(tts_url="")) is None


def test_trailing_slash_of_the_url_is_dropped() -> None:
    # URL は ID トークンの宛先にもなる。Cloud Run は末尾の / 付きの宛先を受け付けない
    assert Settings(tts_url=f"{URL}/").tts_url == URL
