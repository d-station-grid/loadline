"""リクエストの本文の大きさの上限。

FastAPI は認証の依存関数より先に本文を読むので、ルーターの手前で止める。
"""

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# 画面からの JSON。メモの本文の上限（2,000 字）より十分大きい
MAX_BODY_BYTES = 1024 * 1024
# Health Auto Export の JSON。本番の実測の最大は約 830KB
MAX_INGEST_BODY_BYTES = 5 * 1024 * 1024


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
    """上限を超える本文は 413 にする。Content-Length がなくても、読みながら数える。"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] in ("GET", "HEAD", "OPTIONS"):
            await self.app(scope, receive, send)
            return

        limit = _limit_for(scope["path"])
        too_large = JSONResponse({"detail": "request body is too large"}, status_code=413)
        length = _content_length(scope)
        if length is not None and length > limit:
            await too_large(scope, receive, send)
            return

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
            chunks.append(chunk)
            if not message.get("more_body", False):
                break

        body: Message = {"type": "http.request", "body": b"".join(chunks), "more_body": False}
        await self.app(scope, _replay(body, receive), send)


def _replay(first: Message, receive: Receive) -> Receive:
    """最初の 1 回は読んだ内容を返し、そのあとは元の receive に任せる。"""
    pending: list[Message] = [first]

    async def replayed() -> Message:
        if pending:
            return pending.pop()
        return await receive()

    return replayed
