"""api のログの出し方。

各ファイルは logging.getLogger(__name__) で app.* のロガーを使う。何も設定しないと Python の
既定で WARNING 以上しか出ず、dispatch で何人積んだか、などの info が本番のログに残らない。
"""

import logging
import sys

APP_LOGGER = "app"
_FORMAT = "%(levelname)s %(name)s: %(message)s"


class _AppHandler(logging.Handler):
    """configure_logging が付けたハンドラ。2 回呼ばれても二重に付けないための目印も兼ねる。

    書く先は、書くたびに sys.stdout を引く。作ったときの stdout を持ち続けると、pytest が
    テストごとに差し替えて閉じた stdout に書いてしまう。
    """

    def emit(self, record: logging.LogRecord) -> None:
        try:
            sys.stdout.write(self.format(record) + "\n")
            sys.stdout.flush()
        except Exception:
            self.handleError(record)


def configure_logging() -> None:
    """app.* の info 以上を stdout に出す。

    時刻は Cloud Logging が付けるので書かない。親のロガーへも渡したままにする
    （pytest の caplog は親のロガーで受け取る）。
    """
    logger = logging.getLogger(APP_LOGGER)
    logger.setLevel(logging.INFO)
    if any(isinstance(h, _AppHandler) for h in logger.handlers):
        return
    handler = _AppHandler()
    handler.setFormatter(logging.Formatter(_FORMAT))
    logger.addHandler(handler)
