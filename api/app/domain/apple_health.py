"""Health Auto Export から届いた記録の読み方。どれを取り込むかと、値の丸め方。

DB は持ち込まない。届いた文字列や数値を受け取り、取り込む値を返す。
"""

import re
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

APPLE_WATCH = "Apple Watch"
_SPACES = re.compile(r"\s+")

# 種目名（日本語と英語）に含まれる語から loadline の sport へ。ここにない種目は取り込まない。
# Health Auto Export の種目名は「屋外 ラン」「Outdoor Run」のように短いので、
# 「ラン」「Run」で見る（「ランニング」「Running」もこれで当たる）
_SPORTS = {
    "サイクリング": "ride",
    "Cycling": "ride",
    "ラン": "run",
    "Run": "run",
}


def is_apple_watch(source: str | None) -> bool:
    """source が Apple Watch か。空白に \\xa0 が混ざるので、正規化してから比べる。

    時計に名前を付けると「TaketoshiのApple Watch」、VO2max では
    「Apple Watch | TaketoshiのApple Watch」のように届くので、含まれているかで見る。
    """
    if source is None:
        return False
    return APPLE_WATCH in _SPACES.sub(" ", source)


def parse_time(value: str) -> datetime:
    """ "2026-09-13 14:10:45 +0900" を tz 付きの datetime にする。"""
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S %z")


def sport_of(name: str) -> str | None:
    """種目名に含まれる語から ride か run を決める。どちらでもなければ None。"""
    for word, sport in _SPORTS.items():
        if word in name:
            return sport
    return None


def bpm(value: float | None) -> int | None:
    """心拍を整数に丸める。記録がなければ None。"""
    return None if value is None else round(value)


def vo2max_value(qty: float) -> Decimal:
    """VO2max を小数 1 桁に四捨五入する（round は偶数丸めなので使わない）。"""
    return Decimal(str(qty)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
