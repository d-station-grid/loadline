"""ダッシュボードの期間（since と until）の決め方と検査。"""

from datetime import date, timedelta

# 受け付ける最も古い日付。Apple Watch の記録はこれより後で、ウォームアップの日数を引いても
# date の範囲（0001-01-01 から）からあふれない。until は今日で切るので上の端は要らない
EARLIEST_DAY = date(2000, 1, 1)


class InvalidPeriodError(ValueError):
    """since が until より後か、受け付ける範囲の外。field はどのクエリが悪いか。"""

    def __init__(self, field: str, value: date, message: str) -> None:
        super().__init__(message)
        self.field = field
        self.value = value


def needs_first_day(since: date | None, weeks: int | None) -> bool:
    """期間を決めるのに最初のワークアウトの日が要るか。要らなければ DB から読まずに済む。"""
    return since is None and weeks is None


def dashboard_period(
    today: date,
    since: date | None,
    until: date | None,
    weeks: int | None,
    first_day: date | None,
) -> tuple[date, date]:
    """期間（両端を含む）を決める。since がなければ最初のワークアウトの日（first_day）から、
    until がなければ今日まで。

    first_day は needs_first_day が True のときだけ使う。それ以外は None でよい。

    weeks を渡すと、since は until の weeks 週前の日になる。since と一緒には渡さない
    （router で落とす）。

    until は今日で切る。未来の日を負荷 0 で埋めると、体力と疲労が先まで減っていく線が
    予測のように見えるため。期間の検査は既定値を決めて切った後にする。until を省いて
    since に未来の日を渡すと、決める前の検査では逆転を見逃すため。
    """
    until = min(until or today, today)
    if weeks is not None:
        since = until - timedelta(weeks=weeks)
    if since is None:
        # ここに来るのは needs_first_day が True のときだけ（weeks があれば上で決まる）
        since = min(first_day or until, until)
    if since < EARLIEST_DAY:
        raise InvalidPeriodError("since", since, f"since must be on or after {EARLIEST_DAY}")
    if since > until:
        raise InvalidPeriodError(
            "since", since, f"since must be on or before until ({until}, capped at today)"
        )
    return since, until
