"""定型の振り返り。人が書いた英文に、コードで数えた数字だけを埋める。

LLM が使えないときや、作ったセリフを確かめられなかったときの控え。メモは読まない。
埋める数字は、その週の回数、合計の分、休んだ日数の 3 つだけ。体力と疲労の値は入れない。
今の計算の単位では体力が 20 前後になり、一般的な目安の数字と比べると誤解を招くため。

選択肢には必ず軽いもの（休む、軽く流す）を入れる。疲労が溜まっている週には、強度や量を
上げる選択肢を出さない。
"""

from dataclasses import dataclass

from app.domain.situation import Situation, WeekSituation


@dataclass(frozen=True)
class ReviewOption:
    """その週の過ごし方の選択肢。label はボタンの文字、description はその下の 1 文。"""

    label: str
    description: str


@dataclass(frozen=True)
class FallbackReview:
    """アバターが話すセリフと、2〜3 個の選択肢。"""

    script: str
    options: tuple[ReviewOption, ...]


_OPTIONS: dict[Situation, tuple[ReviewOption, ...]] = {
    Situation.NOT_ENOUGH_DATA: (
        ReviewOption("Keep it easy", "Easy sessions while your records build up."),
        ReviewOption("Same as usual", "Train the way you normally do this week."),
    ),
    Situation.NO_TRAINING: (
        ReviewOption("Ease back in", "One short, easy session to get moving again."),
        ReviewOption("Rest a bit more", "Take a few more days off, no pressure."),
        ReviewOption("Pick one day", "Choose one day this week for a session."),
    ),
    Situation.RETURNING: (
        ReviewOption("Keep it easy", "Short, easy sessions while your body readjusts."),
        ReviewOption("Add one session", "One more easy session than last week."),
        ReviewOption("Rest when needed", "Take a day off whenever your legs feel heavy."),
    ),
    Situation.FATIGUED: (
        ReviewOption("Rest fully", "Take a few days off to recover."),
        ReviewOption("Go easy", "Only easy sessions this week."),
        ReviewOption("Short and light", "Keep sessions short and the effort low."),
    ),
    Situation.FRESH: (
        ReviewOption("Add a bit more", "A little more time, or one harder session."),
        ReviewOption("Keep it steady", "Train the same way as last week."),
        ReviewOption("Stay easy", "Keep it easy and save your energy."),
    ),
    Situation.STEADY: (
        ReviewOption("Keep the rhythm", "Train the same way as last week."),
        ReviewOption("Go a bit easier", "Lighter sessions for a few days."),
        ReviewOption("Add one session", "One more easy session this week."),
    ),
}


def fallback_review(week: WeekSituation) -> FallbackReview:
    """判定した状況から、定型のセリフと選択肢を作る。"""
    return FallbackReview(script=_script(week), options=_OPTIONS[week.situation])


def _script(week: WeekSituation) -> str:
    sessions = _count(week.workouts, "session")
    match week.situation:
        case Situation.NOT_ENOUGH_DATA:
            this_week = (
                f"This week you did {sessions}. Keep going,"
                if week.workouts
                else "There are no sessions in yet. Once you start,"
            )
            return (
                "I'm still getting to know your training. "
                "Fitness takes about six weeks of records to read well. "
                f"{this_week} and I'll have more to tell you soon."
            )
        case Situation.NO_TRAINING:
            return (
                "No sessions this week, and that's okay. Life gets busy, and rest counts too. "
                "Your legs have had time to recover, so whenever you're ready, "
                "an easy start is a good way back in."
            )
        case Situation.RETURNING:
            # 中断明けは、その週の最初のワークアウトの前の休みから判定するので必ずある
            assert week.rest_days_before is not None
            return (
                "Welcome back! "
                f"You started training again after {_count(week.rest_days_before, 'day')} off. "
                "Fitness takes a little time to return, so there's no rush. "
                "Starting easy and building slowly is the kindest way back."
            )
        case Situation.FATIGUED:
            return (
                "You've been working hard. Your fatigue is well above your fitness right now, "
                "so your body is asking for some recovery. "
                "A lighter week helps the work you've done sink in."
            )
        case Situation.FRESH:
            return (
                "You're well rested. Your fatigue has dropped below your fitness, "
                "so you have room to train this week. "
                "If you feel good, this is a nice time to add a little more."
            )
        case Situation.STEADY:
            # round は偶数への丸め（150.5 → 150）なので、30 秒を足して切り捨てる
            minutes = _count((week.total_sec + 30) // 60, "minute")
            return (
                f"A steady week. You did {sessions} in {minutes}, "
                "and your fitness and fatigue are in good balance. "
                "Keeping this rhythm is how fitness builds over time."
            )


def _count(n: int, unit: str) -> str:
    """1 なら単数、それ以外は複数にする。例 1 session、3 sessions。"""
    return f"{n} {unit}" if n == 1 else f"{n} {unit}s"
