"""週次レビューを自動で作る時刻か。DB は持ち込まない。

作るのは、週次レビューの曜日の朝 6 時（利用者のタイムゾーン）から、その日の終わりまで。
一度作った週は作り直さないので、前の晩のワークアウトが届くのを待ってから作る
（Health Auto Export はおよそ 4 時間おきに送る）。Scheduler は 1 時間おきに呼ぶので、
その日のうちに一度失敗しても次の回で拾う。その日を逃したら、本人がボタンで作る。
"""

from datetime import datetime
from zoneinfo import ZoneInfo

AUTO_REVIEW_HOUR = 6


def is_auto_review_time(now: datetime, timezone: str, review_weekday: int) -> bool:
    """now（タイムゾーン付き）が、利用者の週次レビューの曜日の 6 時以降か。

    review_weekday は 0 が月曜、6 が日曜。
    """
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    local = now.astimezone(ZoneInfo(timezone))
    return local.weekday() == review_weekday and local.hour >= AUTO_REVIEW_HOUR
