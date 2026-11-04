"""セリフの問いのうち 3 本目で足した 2 つ（offers_more と expression）を本物の Jev に聞き、
期待どおりか確かめる。問いは app/adapters/jev.py の QUESTIONS。

CASES は、問いの期待値。セリフと選択肢を 1 件ずつ聞き、次の 2 つを表にする。
- 増やすことを勧めているか（境目 0.35 以上か）が期待と合うか
- 使う表情（確信度が低ければ relaxed）が、期待する表情のどれかか
問いを変えたら実行し、出た表を PR に貼る。合わない行があれば終了コード 1。
pushes_harder と medical_advice の値も参考に出す（試作で確かめた問いなので、合否は見ない）。
Jev を呼ぶので費用がかかる。テスト（make check）からは呼ばない。

    cd api && TYPESAFE_API_KEY=... uv run python -m scripts.check_line_questions
"""

import asyncio
import sys
from dataclasses import dataclass

from app.adapters.jev import JevLineChecker, jev_checker
from app.core.config import get_settings
from app.domain.expression import Expression, expression_for
from app.domain.fallback_review import ReviewContent, ReviewOption
from app.domain.line_check import YES_CUTOFF, LineCheck

H, R, SA, SU = Expression.HAPPY, Expression.RELAXED, Expression.SAD, Expression.SURPRISED


@dataclass(frozen=True)
class Case:
    script: str
    options: tuple[tuple[str, str], ...]
    offers_more: bool
    expressions: frozenset[Expression]

    @property
    def content(self) -> ReviewContent:
        return ReviewContent(self.script, tuple(ReviewOption(*o) for o in self.options))


CASES: tuple[Case, ...] = (
    # 増やすことを勧めている。押し付けない提案も、選択肢だけでも数える
    Case(
        "A steady week with four rides. If you feel good, you could add one more ride.",
        (("Add one ride", "One extra easy ride this week."), ("Keep it steady", "Same as now.")),
        True,
        frozenset({H, R}),
    ),
    Case(
        "You have room to train. Maybe try a slightly longer ride on Sunday, only if you like.",
        (("Longer Sunday", "Add twenty minutes to Sunday."), ("Stay easy", "Keep it easy.")),
        True,
        frozenset({H, R}),
    ),
    Case(
        "Fatigue is below fitness and things look calm.",
        (("Try intervals", "One harder session with short efforts."), ("Rest", "A day off.")),
        True,
        frozenset({R}),
    ),
    # 増やすことを勧めていない。同じ量、軽く、休む、休み明けの短く軽い 1 回
    Case(
        "Your knee has been bothering you, so let's keep things gentle this week.",
        (("Rest fully", "Take a few days off."), ("Go easy", "Only easy sessions.")),
        False,
        frozenset({SA, R}),
    ),
    Case(
        "No sessions this week, and that's okay. When you're ready, one short easy ride helps.",
        (("Ease back in", "One short, easy session."), ("Rest a bit more", "No pressure.")),
        False,
        frozenset({SA, R}),
    ),
    Case(
        "Five sessions and your best week yet. Keep the same rhythm, it is working.",
        (("Keep the rhythm", "Train the same way."), ("Go a bit easier", "Lighter days.")),
        False,
        frozenset({H}),
    ),
    Case(
        "Welcome back after twenty days off! Starting easy is the kindest way back.",
        (("Keep it easy", "Short, easy sessions."), ("Same as this week", "Same amount.")),
        False,
        frozenset({H, SU}),
    ),
)


@dataclass(frozen=True)
class Result:
    case: Case
    # 確かめられなければ None
    check: LineCheck | None

    @property
    def offers_more_ok(self) -> bool:
        return self.check is not None and (self.check.offers_more >= YES_CUTOFF) is (
            self.case.offers_more
        )

    @property
    def expression(self) -> Expression | None:
        return None if self.check is None else expression_for(self.check.expression)

    @property
    def ok(self) -> bool:
        return self.offers_more_ok and self.expression in self.case.expressions


async def run(checker: JevLineChecker, cases: tuple[Case, ...] = CASES) -> list[Result]:
    """1 件ずつ、順に聞く。"""
    return [Result(case, await checker.check(case.content)) for case in cases]


def render(results: list[Result]) -> str:
    """PR に貼る Markdown の表。"""
    lines = [
        "| セリフ | 増やす（期待） | offers_more | 表情（期待） | 表情 | pushes / medical | 合う |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        expected_more = "勧める" if r.case.offers_more else "勧めない"
        expected_faces = ", ".join(sorted(e.value for e in r.case.expressions))
        if r.check is None:
            cells = ["確かめられない"] * 3
        else:
            answer = r.check.expression
            face = "答えなし" if answer is None else f"{answer.choice} {answer.confidence:.2f}"
            cells = [
                f"{r.check.offers_more:.2f}",
                f"{r.expression} ({face})",
                f"{r.check.pushes_harder:.2f} / {r.check.medical_advice:.2f}",
            ]
        lines.append(
            f"| {r.case.script} | {expected_more} | {cells[0]} | {expected_faces} | {cells[1]} "
            f"| {cells[2]} | {'✓' if r.ok else '✗'} |"
        )
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
