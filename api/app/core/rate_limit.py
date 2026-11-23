"""書き込みの回数の上限。カウントはサーバーのメモリに持つ（api は 1 台で動かす前提）。

再起動するとカウントは消える。連打を抑えるためのもので、厳密な課金や割り当てには使わない。
"""

import math
import threading
import time
from collections.abc import Callable

WINDOW_SEC = 60.0
# 画面からの書き込み。普通の操作では届かない回数
WRITE_LIMIT_PER_WINDOW = 60
# Health Auto Export からの取り込み。本番の実測は 1 分に最大 9 回
INGEST_LIMIT_PER_WINDOW = 60
# この数を超えたら、期限の切れたカウントを捨てる
_PRUNE_ABOVE = 10_000


class RateLimiter:
    """キーごとに、固定の時間枠の中で回数を数える。同期の依存関数からも呼ぶのでロックする。"""

    def __init__(
        self,
        limit: int,
        window_sec: float = WINDOW_SEC,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._limit = limit
        self._window_sec = window_sec
        self._clock = clock
        self._lock = threading.Lock()
        # キー → (時間枠の始まり, 回数)
        self._windows: dict[str, tuple[float, int]] = {}

    def hit(self, key: str) -> int | None:
        """1 回数える。上限の内なら None、超えたら次に試せるまでの秒数（1 以上）。"""
        with self._lock:
            now = self._clock()
            if len(self._windows) > _PRUNE_ABOVE:
                self._windows = {
                    k: v for k, v in self._windows.items() if now - v[0] < self._window_sec
                }
            started, count = self._windows.get(key, (now, 0))
            if now - started >= self._window_sec:
                started, count = now, 0
            if count >= self._limit:
                return max(1, math.ceil(self._window_sec - (now - started)))
            self._windows[key] = (started, count + 1)
            return None
