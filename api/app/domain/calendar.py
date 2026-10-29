"""利用者のタイムゾーンでの日付と時刻。

「今日」「その日の 0 時」は利用者の設定のタイムゾーンで決める。端末やサーバーの
タイムゾーンで決めると、境目の 1 日がずれるため。DB は持ち込まない。
"""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo


def today_in(tz: ZoneInfo, now: datetime | None = None) -> date:
    """tz での今日。now を省けば今の時刻から決める。"""
    return (now or datetime.now(tz)).astimezone(tz).date()


def today_for(timezone: str, now: datetime | None = None) -> date:
    """利用者の設定のタイムゾーン（"Asia/Tokyo" など）での今日。"""
    return today_in(ZoneInfo(timezone), now)


def start_of_day(day: date, tz: ZoneInfo) -> datetime:
    """tz でのその日の 0 時。"""
    return datetime.combine(day, time.min, tzinfo=tz)


def since_for_weeks(weeks: int, tz: ZoneInfo, now: datetime | None = None) -> datetime:
    """「直近 N 週」の始まり。利用者のタイムゾーンの今日から N 週前の日の 0 時。

    端末の日付で決めると、端末と設定のタイムゾーンがずれたときに境目の 1 日がずれるため、
    api で決める。ダッシュボードの weeks と同じ日から始まる。
    """
    return start_of_day(today_in(tz, now) - timedelta(weeks=weeks), tz)
