"""メモの問い（app/adapters/jev.py の NOTE_QUESTIONS）を本物の Jev に聞き、期待どおりか確かめる。

CASES は、問いの期待値。メモ 1 件ずつ聞き、体調のフラグが期待と合うかを表にする。
問いを変えたら実行し、出た表を PR に貼る。合わない行があれば終了コード 1。
Jev を呼ぶので費用がかかる。テスト（make check）からは呼ばない。

    cd api && TYPESAFE_API_KEY=... uv run python -m scripts.check_note_question
"""

import asyncio
import sys
from dataclasses import dataclass
from datetime import date

from app.adapters.jev import JevLineChecker, jev_checker
from app.core.config import get_settings
from app.domain.note_check import NoteCheck, health_flag
from app.domain.review_prompt import NoteForReview


@dataclass(frozen=True)
class Case:
    body: str
    flag: bool


CASES: tuple[Case, ...] = (
    # 今ある痛み、けが、病気。良くなってきた、治療中も立てる
    Case("Knee hurts on stairs.", True),
    Case("腰が痛い。", True),
    Case("Caught a cold and stayed home.", True),
    Case("熱があって休んだ。", True),
    Case("Back pain is getting better. Saw a physio today.", True),
    Case("膝が少し痛むけど走った。", True),
    # 治った、練習の後の普通の筋肉痛、疲れ、寝不足、脚の重さ、関係のないこと
    Case("膝はもう大丈夫。", False),
    Case("Knee pain is gone now.", False),
    Case("Quads sore after the long ride.", False),
    Case("筋肉痛。", False),
    Case("Legs heavy on the climb.", False),
    Case("寝不足。", False),
    Case("Busy week at work.", False),
)

DAY = date(2026, 10, 12)


@dataclass(frozen=True)
class Result:
    case: Case
    # 確かめられなければ None
    mentions_health: float | None

    @property
    def ok(self) -> bool:
        if self.mentions_health is None:
            return False
        return health_flag(NoteCheck(mentions_health=self.mentions_health)) is self.case.flag


async def run(checker: JevLineChecker, cases: tuple[Case, ...] = CASES) -> list[Result]:
    """メモ 1 件ずつ、順に聞く。"""
    results = []
    for case in cases:
        check = await checker.check_notes([NoteForReview(DAY, None, case.body)])
        results.append(Result(case, None if check is None else check.mentions_health))
    return results


def render(results: list[Result]) -> str:
    """PR に貼る Markdown の表。"""
    lines = ["| メモ | 期待 | mentions_health | 合う |", "|---|---|---|---|"]
    for r in results:
        yes = "確かめられない" if r.mentions_health is None else f"{r.mentions_health:.2f}"
        expected = "立てる" if r.case.flag else "立てない"
        lines.append(f"| {r.case.body} | {expected} | {yes} | {'✓' if r.ok else '✗'} |")
    return "\n".join(lines)


async def main() -> int:
    checker = jev_checker(get_settings())
    if checker is None:
        print("TYPESAFE_API_KEY が空か、Jev のクライアントを作れません", file=sys.stderr)
        return 2
    results = await run(checker)
    print(render(results))
    return 0 if all(r.ok for r in results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
