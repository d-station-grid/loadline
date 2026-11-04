"""その週のメモが痛みや病気に触れているかを Jev で確かめた結果と、体調のフラグ。

Jev は「はい」の確率（0〜1）を返すだけで、フラグを立てるかはここ（コード）で決める。
フラグが立った週は、量や強度を上げる選択肢を出さない。出すかどうかも、LLM への指示に
任せずコードで決める（review_prompt の may_offer_more、定型の選択肢）。
"""

from collections.abc import Sequence
from dataclasses import dataclass

from app.domain.line_check import YES_CUTOFF
from app.domain.review_prompt import NoteForReview


@dataclass(frozen=True)
class NoteCheck:
    """Jev の答え。「はい」の確率（0〜1）。"""

    # 痛み、けが、病気、体の不調に触れている
    mentions_health: float


def notes_to_check(notes: Sequence[NoteForReview]) -> str:
    """確かめる文。メモを日付順に 1 行ずつ、日付、ラベル、本文の順でつなぐ。"""
    return "\n".join(
        " ".join(part for part in (n.day.isoformat(), n.label, n.body) if part)
        for n in sorted(notes, key=lambda n: n.day)
    )


def health_flag(check: NoteCheck) -> bool:
    """体調のフラグ。セリフの確認と同じ境目で、安全側（立てる側）に倒す。"""
    return check.mentions_health >= YES_CUTOFF
