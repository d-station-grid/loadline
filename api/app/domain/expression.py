"""アバターの表情。セリフに合う表情を Jev に選んでもらい、使うかどうかはここ（コード）で決める。

値は VRM の表情の名前に合わせる。怒った顔（angry）は、励ます相手には使わないので置かない。
確信度が低いとき、答えがないとき、知らない表情のときは、落ち着いた顔（relaxed）にする。
定型のセリフも relaxed にする。
"""

import math
from dataclasses import dataclass
from enum import StrEnum


class Expression(StrEnum):
    HAPPY = "happy"
    RELAXED = "relaxed"
    SAD = "sad"
    SURPRISED = "surprised"


# 表情が決まらないときの顔
DEFAULT_EXPRESSION = Expression.RELAXED

# Jev が選んだ表情を使う確信度の下限。これより低ければ relaxed にする
CONFIDENCE_CUTOFF = 0.6

_NAMES = frozenset(e.value for e in Expression)


@dataclass(frozen=True)
class ExpressionAnswer:
    """Jev が選んだ表情の名前と、その確信度（0〜1）。名前は確かめていない生の値。"""

    choice: str
    confidence: float


def expression_for(answer: ExpressionAnswer | None) -> Expression:
    """使う表情。答えがない、知らない名前、確信度が低い（NaN を含む）なら relaxed。"""
    if answer is None or answer.choice not in _NAMES:
        return DEFAULT_EXPRESSION
    if not (math.isfinite(answer.confidence) and answer.confidence >= CONFIDENCE_CUTOFF):
        return DEFAULT_EXPRESSION
    return Expression(answer.choice)
