"""Google Cloud Text-to-Speech（Gemini の TTS）に、日本語のセリフを読み上げてもらう。

口調の指示（prompt）と読む文（text）は、別々の欄で渡す。Vertex AI の generateContent で
指示を文に混ぜると、指示まで読み上げたり、言葉を足したり、文を繰り返したりしたため。
欄を分けられるのは Cloud Text-to-Speech の text:synthesize で、使えるモデルは 2.5 世代だけ。

認証は Application Default Credentials のアクセストークン。本番は Cloud Run の
サービスアカウント（loadline-api）。キーは使わない。

Cloud Text-to-Speech は利用額の上限（自動停止）の対象外なので、割り当て（1 分あたりの
リクエスト数）を下げて歯止めにしている。混雑（429）や一時的な障害（5xx）、通信の失敗は
1 回だけ間を空けてやり直す。全体で timeout_sec を超えるか、読めなければ None を返し、
呼ぶ側は音声なしにする。
"""

import asyncio
import base64
import binascii
import logging
import threading
from collections.abc import Awaitable, Callable

import google.auth
import httpx
from google.auth.credentials import Credentials
from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import Request

from app.core.config import Settings

logger = logging.getLogger(__name__)

SYNTHESIZE_URL = "https://texttospeech.googleapis.com/v1/text:synthesize"
LANGUAGE_CODE = "ja-JP"
# 口調の指示。読む文とは別の欄で渡すので、読み上げられない
PROMPT = "Speak as a bright, cute anime girl cheerfully encouraging a runner."
# 最初の 1 回を含めて試す回数と、やり直す前に待つ秒数
ATTEMPTS = 2
RETRY_WAIT_SEC = 5.0
# 待てば直る見込みのある応答。429 は混雑か割り当ての超過、5xx は一時的な障害
_RETRY_CODES = frozenset({429, 500, 502, 503, 504})
_SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]


class AccessTokens:
    """Google の API を呼ぶアクセストークン。期限までは使い回す。"""

    def __init__(self) -> None:
        self._credentials: Credentials | None = None
        # to_thread の別のスレッドから同時に来ても、取り直すのは 1 回にする
        self._lock = threading.Lock()

    def _token(self) -> str:
        with self._lock:
            if self._credentials is None:
                self._credentials, _ = google.auth.default(scopes=_SCOPES)
            if not self._credentials.valid:
                self._credentials.refresh(Request())  # type: ignore[no-untyped-call]
            return str(self._credentials.token)

    async def __call__(self) -> str:
        return await asyncio.to_thread(self._token)


class GoogleVoice:
    def __init__(
        self,
        model: str,
        voice_name: str,
        token: Callable[[], Awaitable[str]],
        timeout_sec: float,
        client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        """model は gemini-2.5-pro-tts など、voice_name は Leda など。token は付ける
        アクセストークンを返す。client と sleep は、テストで差し替える。"""
        self._request = {
            "voice": {"languageCode": LANGUAGE_CODE, "name": voice_name, "modelName": model},
            "audioConfig": {"audioEncoding": "MP3"},
        }
        self._token = token
        self._timeout_sec = timeout_sec
        self._client = client or httpx.AsyncClient(timeout=timeout_sec)
        self._sleep = sleep

    async def speak(self, text: str) -> bytes | None:
        """text を読み上げた MP3。読めなければ None。"""
        try:
            async with asyncio.timeout(self._timeout_sec):
                return await self._try(text)
        except TimeoutError:
            logger.warning("google tts: gave up after %s seconds", self._timeout_sec)
            return None

    async def _try(self, text: str) -> bytes | None:
        body = {**self._request, "input": {"prompt": PROMPT, "text": text}}
        for attempt in range(1, ATTEMPTS + 1):
            if attempt > 1:
                await self._sleep(RETRY_WAIT_SEC)
            try:
                token = await self._token()
            except GoogleAuthError as error:
                logger.error("google tts: could not get an access token: %r", error)
                return None
            try:
                response = await self._client.post(
                    SYNTHESIZE_URL, json=body, headers={"Authorization": f"Bearer {token}"}
                )
            except httpx.HTTPError as error:
                logger.warning("google tts: attempt %d failed: %r", attempt, error)
                continue
            if response.status_code == httpx.codes.OK:
                return _audio(response)
            if response.status_code in _RETRY_CODES:
                logger.warning("google tts: attempt %d got %d", attempt, response.status_code)
                continue
            # 権限（403）やリクエストの誤り（400）は、やり直しても変わらない。
            # 応答の本文にはセリフが入らないので、理由を見られるように残す
            logger.error(
                "google tts: rejected with %d: %s", response.status_code, response.text[:300]
            )
            return None
        logger.warning("google tts: gave up after %d attempts", ATTEMPTS)
        return None


def _audio(response: httpx.Response) -> bytes | None:
    """応答の audioContent（base64）を音声にする。なければ、読めなければ None。"""
    try:
        content = response.json().get("audioContent")
        return base64.b64decode(content, validate=True) if content else None
    except (ValueError, binascii.Error, AttributeError) as error:
        logger.error("google tts: unexpected response: %r", error)
        return None


def google_voice(
    settings: Settings, token: Callable[[], Awaitable[str]] | None = None
) -> GoogleVoice | None:
    """設定から作る。GOOGLE_TTS_MODEL が空なら None（日本語は声にしない）。
    ここではまだトークンを取らない。"""
    if not settings.google_tts_model:
        return None
    return GoogleVoice(
        settings.google_tts_model,
        settings.google_tts_voice,
        token or AccessTokens(),
        settings.google_tts_timeout_sec,
    )
