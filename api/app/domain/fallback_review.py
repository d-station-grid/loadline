"""定型の週次レビュー。人が書いた英文に、コードで数えた数字だけを埋める。

LLM が使えないときや、作ったセリフを確かめられなかったときの控え。メモは読まない。
埋める数字は、その週の回数、合計の分、休んだ日数の 3 つだけ。体力と疲労の値は入れない。
今の計算の単位では体力が 20 前後になり、一般的な目安の数字と比べると誤解を招くため。

選択肢には必ず軽いもの（休む、軽く流す）を入れる。疲労が高い週には、強度や量を上げる
選択肢を出さない。判定は「疲労」より先に「記録が足りない」「走れなかった週」「中断明け」を
当てるので、この 3 つも疲労が高いことがある。増やす選択肢を置くのは「休めている」と
「順調」だけにする。メモの体調のフラグが立った週は、その 2 つからも増やす選択肢を外し、
セリフも増やすことを勧めない言い方にする。
フラグはメモを Jev で確かめた答えからコードで決めたもので、ここではメモそのものは読まない。
"""

from dataclasses import dataclass

from app.domain.effort import NO_EFFORT, Effort, Volume
from app.domain.situation import Situation, WeekSituation


@dataclass(frozen=True)
class ReviewOption:
    """その週の過ごし方の選択肢。label はボタンの文字、description はその下の 1 文。"""

    label: str
    description: str


@dataclass(frozen=True)
class ReviewContent:
    """アバターが話すセリフと、2〜3 個の選択肢。定型でも、LLM が書いたものでも同じ形。"""

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


# 量や強度を上げる選択肢。体調のフラグが立った週と、練習の量が多めだった週は外す。
# 外しても 2 個は残る
_ADDS_LOAD = frozenset({"Add a bit more", "Add one session"})

# 中強度寄りの週に出す選択肢。中強度の一部を低強度に置き換える。足す形にしない
# （量が多めの週の「増やさない」とぶつかるため）
_SWAP_IN_EASY = ReviewOption("Swap in easy days", "Turn some moderate sessions into easy ones.")

# 「今と同じ」選択肢。中強度寄りの週は、今の配分を続けることになるので、置き換える選択肢と替える
_SAME_AS_NOW = frozenset(
    {"Same as usual", "Same as this week", "Keep it steady", "Keep the rhythm"}
)

# 練習の量と強度の配分の一言。入れるのは、疲労・休めている・順調の週だけ（記録が
# 足りない週と中断明けは、その週の事情を話す方を優先する）。言うのは判定で確かめられる
# 事実だけにする。
#
# 高強度・多め・中強度寄りは、助言の向き（控える、なじませる、置き換える）が状況の締めと
# そろうので、締めの 1 文と入れ替えて長さを 15 秒ほどに保つ。
# 高強度は「負荷が普段より多く、高強度の時間も増えた」までしか言わない。判定は増え方の比べ
# だけで、負荷の増えた分の大半が高強度だったとは確かめていないため（過去に高強度が 0 分なら、
# 1 分増えただけでも立つ）。
_HARD_WENT_UP = (
    "Your load was well above usual, and hard-effort time went up too, so ease off hard sessions."
)
_HEAVY = "You did well above your usual load this week, so let that work sink in."
_MOSTLY_MODERATE = (
    "Much of your time was at moderate effort, so swapping some for easy sessions can help."
)
# いつもどおり・少なめは、状況の締め（回復を勧める、増やしてよい、体の声を聞く）を消すと
# 助言とずれるので、締めは残し、その直前に事実だけの短い文を足す。いちばん長い定型
# （34 語）に足しても 40 語に収まる長さにする
_USUAL = "Your load matched your usual weeks."
_LIGHT = "Your load was lighter than usual."


def fallback_review(
    week: WeekSituation, health_flag: bool = False, effort: Effort = NO_EFFORT
) -> ReviewContent:
    """判定した状況から、定型のセリフと選択肢を作る。

    health_flag はメモの体調のフラグ。メモを確かめていなければ False のまま呼ぶ。
    effort は練習の量と強度の配分の判定。量が多めの週は、量を増やす選択肢を出さず、
    セリフも増やすことを勧めない言い方にする。中強度寄りの週は、「今と同じ」選択肢を
    中強度を低強度に置き換える選択肢に替える。疲労・休めている・順調の週は、セリフの締めを
    量と配分の一言に入れ替える。
    """
    holds_back = health_flag or effort.volume is Volume.HEAVY
    options = _OPTIONS[week.situation]
    if holds_back:
        options = tuple(o for o in options if o.label not in _ADDS_LOAD)
    if effort.mostly_moderate:
        options = _with_swap(options)
    replacement, fact = _effort_line(effort)
    return ReviewContent(script=_script(week, holds_back, replacement, fact), options=options)


def _with_swap(options: tuple[ReviewOption, ...]) -> tuple[ReviewOption, ...]:
    """「今と同じ」選択肢を、中強度を低強度に置き換える選択肢に替える。なければ、3 個なら
    最後の 1 個を替え、2 個なら足す。休む・軽く流す選択肢は残す。"""
    same = [i for i, o in enumerate(options) if o.label in _SAME_AS_NOW]
    if same:
        i = same[0]
    elif len(options) >= 3:
        i = len(options) - 1
    else:
        return (*options, _SWAP_IN_EASY)
    return (*options[:i], _SWAP_IN_EASY, *options[i + 1 :])


def _effort_line(effort: Effort) -> tuple[str | None, str | None]:
    """量と配分の一言。(締めと入れ替える文, 締めの前に足す文) のどちらか 1 つだけを返す。

    量が多めで高強度の時間も増えた > 多め > 中強度寄り > いつもどおり > 少なめ の順に 1 つ選ぶ。
    何も判定できなければ (None, None)（締めの 1 文をそのまま使う）。
    """
    if effort.hard_went_up:
        return _HARD_WENT_UP, None
    if effort.volume is Volume.HEAVY:
        return _HEAVY, None
    if effort.mostly_moderate:
        return _MOSTLY_MODERATE, None
    if effort.volume is Volume.USUAL:
        return None, _USUAL
    if effort.volume is Volume.LIGHT:
        return None, _LIGHT
    return None, None


def _script(
    week: WeekSituation,
    holds_back: bool,
    replacement: str | None = None,
    fact: str | None = None,
) -> str:
    """holds_back は、量を増やすことを勧めない週（体調のフラグか、量が多め）。
    疲労・休めている・順調の週は、replacement があれば締めの 1 文と入れ替え、fact があれば
    締めの直前に足す。"""

    def closing(default: str) -> str:
        return " ".join(part for part in (fact, replacement or default) if part)

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
                + closing("A lighter week helps the work you've done sink in.")
            )
        case Situation.FRESH if holds_back:
            # 選択肢と食い違わないように、増やすことを勧めない。痛みや病気がある週か、メモを
            # 確かめられなかった週か、量が多めだった週。休めた、回復したとは言い切らず、
            # メモの中身にも触れない
            return (
                "Your fatigue is below your fitness right now. "
                "Numbers are only part of the picture, though. "
                + closing(
                    "This week, keep things comfortable, take it at your own pace, "
                    "and listen to how your body feels."
                )
            )
        case Situation.FRESH:
            return (
                # 判定は今の疲労と体力の比べだけなので、下がったとは言わない
                "You're well rested. Your fatigue is below your fitness right now, "
                "so you have room to train this week. "
                + closing("If you feel good, this is a nice time to add a little more.")
            )
        case Situation.STEADY:
            # round は偶数への丸め（150.5 → 150）なので、30 秒を足して切り捨てる
            minutes = _count((week.total_sec + 30) // 60, "minute")
            return (
                f"A steady week. You did {sessions} in {minutes}, "
                "and your fitness and fatigue are in good balance. "
                + closing("Keeping this rhythm is how fitness builds over time.")
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
