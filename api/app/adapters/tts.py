"""tts（Kokoro、Cloud Run）に、振り返りのセリフを読み上げてもらう。

tts は認証が必須なので、tts の URL を宛先（audience）にした ID トークンを付ける。本番は
Cloud Run のサービスアカウント（loadline-api）で、tts の run.invoker が要る。

tts は 1 台で同時に 1 件しか読まず、上限は 2 台。空きが出なければ Cloud Run が 429 を返す
ので、間を空けてやり直す。起動の途中の 5xx と通信の失敗も同じ。試すのは最初の 1 回を含めて
3 回まで。全体で timeout_sec を超えるか、読めなければ None を返し、呼ぶ側は音声なしにする。
"""

import asyncio
import logging
import threading
from collections.abc import Awaitable, Callable

import httpx
from google.auth.credentials import Credentials
from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import Request
from google.oauth2 import id_token

from app.core.config import Settings

logger = logging.getLogger(__name__)

# 最初の 1 回を含めて試す回数
ATTEMPTS = 3
# やり直す前に待つ秒数。読み上げ 1 件は数秒〜十数秒なので、そのあいだに空きが出るのを待つ
RETRY_WAITS_SEC = (5.0, 10.0)
# 待てば直る見込みのある応答。429 は空きがない、5xx は起動の途中や一時的な障害
_RETRY_CODES = frozenset({429, 500, 502, 503, 504})


class IdTokens:
    """tts を宛先にした ID トークン。期限（1 時間）までは使い回す。

    本番は Cloud Run のメタデータサーバーから取る。手元の利用者の資格情報では取れない。
    """

    def __init__(self, audience: str) -> None:
        self._audience = audience
        self._credentials: Credentials | None = None
        # to_thread の別のスレッドから同時に来ても、取り直すのは 1 回にする
        self._lock = threading.Lock()

    def _token(self) -> str:
        with self._lock:
            if self._credentials is None:
                self._credentials = id_token.fetch_id_token_credentials(  # type: ignore[no-untyped-call]
                    self._audience, Request()
                )
            if not self._credentials.valid:
                self._credentials.refresh(Request())
            return str(self._credentials.token)

    async def __call__(self) -> str:
        return await asyncio.to_thread(self._token)


class KokoroVoice:
    def __init__(
        self,
        base_url: str,
        token: Callable[[], Awaitable[str]],
        timeout_sec: float,
        client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        """base_url は tts の URL（末尾の / なし）。token は付ける ID トークンを返す。
        client と sleep は、テストで差し替える。"""
        self._speak_url = f"{base_url}/speak"
        self._token = token
        self._timeout_sec = timeout_sec
        self._client = client or httpx.AsyncClient(timeout=timeout_sec)
        self._sleep = sleep

    async def speak(self, text: str) -> bytes | None:
        """text を読み上げた WAV。読めなければ None。"""
        try:
            async with asyncio.timeout(self._timeout_sec):
                return await self._try(text)
        except TimeoutError:
            logger.warning("tts: gave up after %s seconds", self._timeout_sec)
            return None

    async def _try(self, text: str) -> bytes | None:
        for attempt in range(1, ATTEMPTS + 1):
            if attempt > 1:
                await self._sleep(RETRY_WAITS_SEC[attempt - 2])
            try:
                token = await self._token()
            except GoogleAuthError as error:
                logger.error("tts: could not get an ID token: %r", error)
                return None
            try:
                response = await self._client.post(
                    self._speak_url,
                    json={"text": text},
                    headers={"Authorization": f"Bearer {token}"},
                )
            except httpx.HTTPError as error:
                logger.warning("tts: attempt %d failed: %r", attempt, error)
                continue
            if response.status_code == httpx.codes.OK:
                return response.content
            if response.status_code in _RETRY_CODES:
                logger.warning("tts: attempt %d got %d", attempt, response.status_code)
                continue
            # 認証（401、403）やリクエストの誤り（422）は、やり直しても変わらない
            logger.error("tts: rejected with %d", response.status_code)
            return None
        logger.warning("tts: gave up after %d attempts", ATTEMPTS)
        return None


def kokoro_voice(settings: Settings) -> KokoroVoice | None:
    """設定から作る。TTS_URL が空なら None（声にしない）。ここではまだトークンを取らない。"""
    if not settings.tts_url:
        return None
    return KokoroVoice(settings.tts_url, IdTokens(settings.tts_url), settings.tts_timeout_sec)
