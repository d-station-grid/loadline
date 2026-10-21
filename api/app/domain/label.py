"""メモのラベルの長さ。チャートの吹き出しに収まるよう、文字数ではなく幅で数える。"""

import unicodedata

# 半角なら 12 文字、全角なら 6 文字
MAX_LABEL_WIDTH = 12


def display_width(text: str) -> int:
    """全角（F）と幅広（W）を 2、それ以外を 1 として数える。

    「①」や「α」のように環境で幅が変わる文字（A）は 1 とする。厳しすぎない側に寄せる。
    web の lib/label.ts も同じ数え方にしてある。
    web の範囲の表は scripts/export_label_widths.py で作る。
    """
    return sum(2 if unicodedata.east_asian_width(c) in ("F", "W") else 1 for c in text)
