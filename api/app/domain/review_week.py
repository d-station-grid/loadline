"""振り返る 7 日間を決める。日付は呼ぶ側が利用者のタイムゾーンで決めたもの。"""

from datetime import date, timedelta

from app.domain.situation import DAYS_IN_WEEK


def review_period(today: date, review_weekday: int) -> tuple[date, date]:
    """今日以前でいちばん近い振り返りの曜日の、前日までの 7 日間（両端を含む）。

    review_weekday は 0 が月曜、6 が日曜。今日が振り返りの曜日なら、昨日までの 7 日間。
    例: 曜日が月曜で今日が 2026-10-24（土）なら、10/19（月）の回で 10/12〜10/18。
    """
    if not 0 <= review_weekday < DAYS_IN_WEEK:
        raise ValueError(f"review_weekday must be between 0 and {DAYS_IN_WEEK - 1}")
    review_day = today - timedelta(days=(today.weekday() - review_weekday) % DAYS_IN_WEEK)
    return review_day - timedelta(days=DAYS_IN_WEEK), review_day - timedelta(days=1)
