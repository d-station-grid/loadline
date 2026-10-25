"""定型の振り返り。人が書いた英文に、コードで数えた数字だけを埋める。

LLM が使えないときや、作ったセリフを確かめられなかったときの控え。メモは読まない。
埋める数字は、その週の回数、合計の分、休んだ日数の 3 つだけ。体力と疲労の値は入れない。
今の計算の単位では体力が 20 前後になり、一般的な目安の数字と比べると誤解を招くため。

選択肢には必ず軽いもの（休む、軽く流す）を入れる。疲労が高い週には、強度や量を上げる
選択肢を出さない。判定は「疲労」より先に「記録が足りない」「走れなかった週」「中断明け」を
当てるので、この 3 つも疲労が高いことがある。増やす選択肢を置くのは「休めている」と
「順調」だけにする。
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
        # 中断明けは疲労の判定より先に当たり、疲労が高い週もここに来るので、増やす選択肢は置かない
        ReviewOption("Same as this week", "Keep the same amount as this week."),
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
            return _not_enough_data_script(week, sessions)
        case Situation.NO_TRAINING:
            # 走れなかった週は負荷を見ずに判定するので、回復したとは言い切らない
            return (
                "No sessions this week, and that's okay. "
                "Life gets busy, and rest is part of training too. "
                "Whenever you're ready, an easy session is a gentle way to get moving again."
            )
        case Situation.RETURNING:
            # 中断明けは、その週の最初のワークアウトの前の休みから判定するので必ずある。
            # ないのは判定と材料の食い違い。assert は最適化の実行で消えるので使わない
            if week.rest_days_before is None:
                raise ValueError("rest_days_before is required for a returning week")
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
                # 判定は今の疲労と体力の比べだけなので、下がったとは言わない
                "You're well rested. Your fatigue is below your fitness right now, "
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


def _not_enough_data_script(week: WeekSituation, sessions: str) -> str:
    """記録が足りない週。理由が違えば、事実と食い違わないように言い方を変える。

    判定の結果からは、記録の短さと体力が 0 のどちらだったかまでは分からない。
    どちらでも本当になる言い方にする。
    """
    if week.workouts == 0:
        # まだ 1 件も記録がない
        return (
            "I'm still getting to know your training. "
            "Fitness takes about six weeks of records to read well. "
            "There are no sessions in yet. Once you start, I'll have more to tell you soon."
        )
    if week.unknown_load_days > 0 and week.workouts == 1:
        return (
            "This week you did 1 session, but it has no heart rate, "
            "so I can't read your fitness and fatigue clearly. "
            "With heart rate on every session, I'll have more to tell you."
        )
    if week.unknown_load_days > 0:
        return (
            f"This week you did {sessions}, but some of them have no heart rate, "
            "so I can't read your fitness and fatigue clearly. "
            "With heart rate on every session, I'll have more to tell you."
        )
    # 記録が短いか、体力が 0
    return (
        f"This week you did {sessions}. "
        "I can't read your fitness and fatigue clearly yet, "
        "because that takes a few weeks of sessions with heart rate. "
        "Keep going, and I'll have more to tell you soon."
    )


def _count(n: int, unit: str) -> str:
    """1 なら単数、それ以外は複数にする。例 1 session、3 sessions。"""
    return f"{n} {unit}" if n == 1 else f"{n} {unit}s"
