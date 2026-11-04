"""LLM が書いたセリフを Jev で確かめた結果と、話してよいかの判定。

Jev は「はい」の確率（0〜1）を返すだけで、話してよいかはここ（コード）で決める。
確かめる文は、話す部分とボタンに出る選択肢の文をつないだもの。選択肢も画面に出るので、
話す部分と同じ決まりで確かめる。

量や強度を上げることを勧めているか（offers_more）は、増やす選択肢を出してはいけない週
（may_offer_more が false）だけで引っかける。LLM への指示だけに頼らず、コードで止める。
"""

from dataclasses import dataclass

from app.domain.expression import ExpressionAnswer
from app.domain.fallback_review import ReviewContent

# Noul で「はい」とみなす境目。安全側に倒すため、0.5 より低くする。
# Choice（表情）の答えはこの境目では判定しない。expression の expression_for で決める
YES_CUTOFF = 0.35


@dataclass(frozen=True)
class LineCheck:
    """Jev の答え。expression のほかは「はい」の確率（0〜1）。"""

    # 練習を無理強いする（命じる、責める、疲れや痛みを押して続けさせる、休んだ分を取り返させる）
    pushes_harder: float
    # 診断する、薬や治療を勧める、症状を心配ないと言う
    medical_advice: float
    # 量や強度を上げることを勧める（押し付けない提案も含む）
    offers_more: float
    # セリフに合う表情。答えがなければ None（relaxed にする）
    expression: ExpressionAnswer | None


def text_to_check(content: ReviewContent) -> str:
    """確かめる文。話す部分と、選択肢のボタンの文字とその下の 1 文を 1 つにつなぐ。"""
    return " ".join([content.script, *[f"{o.label}: {o.description}" for o in content.options]])


def flagged(check: LineCheck, may_offer_more: bool) -> dict[str, float]:
    """境目以上だった問いの名前と、その「はい」の確率。空なら話してよい。

    may_offer_more が true の週は、増やすことを勧めても引っかけない。
    """
    answers = {"pushes_harder": check.pushes_harder, "medical_advice": check.medical_advice}
    if not may_offer_more:
        answers["offers_more"] = check.offers_more
    return {name: yes for name, yes in answers.items() if yes >= YES_CUTOFF}
