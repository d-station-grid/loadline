"""リクエストの本文の大きさの上限。

FastAPI は認証の依存関数より先に本文を読むので、ルーターの手前で止める。
"""

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# 画面からの JSON。メモの本文の上限（2,000 字）より十分大きい
MAX_BODY_BYTES = 1024 * 1024
# Health Auto Export の JSON。本番の実測の最大は約 830KB
MAX_INGEST_BODY_BYTES = 5 * 1024 * 1024
# 処理中の本文の合計。JSON と Pydantic への変換で本文の約 8 倍のメモリを使う（5MiB で約 41MiB を
# 実測）ので、512MiB の 1 台が同時の大きな本文で落ちないようにする
MAX_INFLIGHT_BODY_BYTES = 16 * 1024 * 1024
BUSY_RETRY_AFTER_SEC = 5


def _limit_for(path: str) -> int:
    return MAX_INGEST_BODY_BYTES if path.rstrip("/") == "/ingest" else MAX_BODY_BYTES


def _content_length(scope: Scope) -> int | None:
    for name, value in scope["headers"]:
        if name == b"content-length":
            try:
                return int(value)
            except ValueError:
                return None
    return None


class BodySizeLimitMiddleware:
    """1 件の上限を超える本文は 413、処理中の合計の上限を超える本文は 503 にする。

    Content-Length がなくても、読みながら数える。合計の枠は、JSON への変換でもメモリを使うので、
    応答が終わるまで持つ。イベントループの中でだけ増減するので、ロックは要らない。
    """

    def __init__(self, app: ASGIApp, max_inflight_bytes: int = MAX_INFLIGHT_BODY_BYTES) -> None:
        self.app = app
        self._max_inflight_bytes = max_inflight_bytes
        self._inflight_bytes = 0

    def _reserve(self, size: int) -> bool:
        if self._inflight_bytes + size > self._max_inflight_bytes:
            return False
        self._inflight_bytes += size
        return True

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] in ("GET", "HEAD", "OPTIONS"):
            await self.app(scope, receive, send)
            return

        limit = _limit_for(scope["path"])
        too_large = JSONResponse({"detail": "request body is too large"}, status_code=413)
        busy = JSONResponse(
            {"detail": "server is busy"},
            status_code=503,
            headers={"Retry-After": str(BUSY_RETRY_AFTER_SEC)},
        )
        length = _content_length(scope)
        if length is not None and length > limit:
            await too_large(scope, receive, send)
            return

        reserved = 0
        try:
            if length is not None:
                if not self._reserve(length):
                    await busy(scope, receive, send)
                    return
                reserved = length

            # 上限まで読んでから、読んだ分をアプリに渡し直す
            chunks: list[bytes] = []
            size = 0
            while True:
                message = await receive()
                if message["type"] != "http.request":
                    # 途中で切断された。そのままアプリに伝える
                    await self.app(scope, _replay(message, receive), send)
                    return
                chunk = message.get("body", b"")
                size += len(chunk)
                if size > limit:
                    await too_large(scope, receive, send)
                    return
                if size > reserved:
                    if not self._reserve(size - reserved):
                        await busy(scope, receive, send)
                        return
                    reserved = size
                chunks.append(chunk)
                if not message.get("more_body", False):
                    break

            body: Message = {"type": "http.request", "body": b"".join(chunks), "more_body": False}
            await self.app(scope, _replay(body, receive), send)
        finally:
            self._inflight_bytes -= reserved


def _replay(first: Message, receive: Receive) -> Receive:
    """最初の 1 回は読んだ内容を返し、そのあとは元の receive に任せる。"""
    pending: list[Message] = [first]

    async def replayed() -> Message:
        if pending:
            return pending.pop()
        return await receive()

    return replayed
