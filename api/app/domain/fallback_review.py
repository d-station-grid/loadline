"""定型の週次レビュー。人が書いた英文と日本文に、コードで数えた数字だけを埋める。

LLM が使えないときや、作ったセリフを確かめられなかったときの控え。メモは読まない。
埋める数字は、その週の回数、合計の分、休んだ日数の 3 つだけ。体力と疲労の値は入れない。
今の計算の単位では体力が 20 前後になり、一般的な目安の数字と比べると誤解を招くため。

選択肢には必ず軽いもの（休む、軽く流す）を入れる。疲労が高い週には、強度や量を上げる
選択肢を出さない。判定は「疲労」より先に「記録が足りない」「走れなかった週」「中断明け」を
当てるので、この 3 つも疲労が高いことがある。増やす選択肢を置くのは「休めている」と
「順調」だけにする。メモの体調のフラグが立った週は、その 2 つからも増やす選択肢を外し、
セリフも増やすことを勧めない言い方にする。
フラグはメモを Jev で確かめた答えからコードで決めたもので、ここではメモそのものは読まない。

選択肢は、言語によらない名前（キー）で選び分け、最後に利用者の言語の文言にする。
"""

from dataclasses import dataclass

from app.domain.effort import NO_EFFORT, Effort, Volume
from app.domain.language import DEFAULT_LANGUAGE, Language
from app.domain.situation import Situation, WeekSituation


@dataclass(frozen=True)
class ReviewOption:
    """その週の過ごし方の選択肢。label はボタンの文字、description はその下の 1 文。"""

    label: str
    description: str


@dataclass(frozen=True)
class ReviewContent:
    """アバターが話すセリフと、2〜3 個の選択肢。定型でも、LLM が書いたものでも同じ形。

    detail は画面で読む長めの文（話さない）。LLM が書き、Jev で確かめられたときだけ入る。
    定型にはない。
    """

    script: str
    options: tuple[ReviewOption, ...]
    detail: str | None = None


# 状況ごとの選択肢。並びはボタンの順
_OPTIONS: dict[Situation, tuple[str, ...]] = {
    Situation.NOT_ENOUGH_DATA: ("keep_easy_while_records", "same_as_usual"),
    Situation.NO_TRAINING: ("ease_back_in", "rest_more", "pick_one_day"),
    # 中断明けは疲労の判定より先に当たり、疲労が高い週もここに来るので、増やす選択肢は置かない
    Situation.RETURNING: ("keep_easy_while_readjusting", "same_as_this_week", "rest_when_needed"),
    Situation.FATIGUED: ("rest_fully", "go_easy", "short_and_light"),
    Situation.FRESH: ("add_a_bit_more", "keep_it_steady", "stay_easy"),
    Situation.STEADY: ("keep_the_rhythm", "go_a_bit_easier", "add_one_session"),
}

_OPTION_TEXT: dict[Language, dict[str, ReviewOption]] = {
    Language.EN: {
        "keep_easy_while_records": ReviewOption(
            "Keep it easy", "Easy sessions while your records build up."
        ),
        "same_as_usual": ReviewOption("Same as usual", "Train the way you normally do this week."),
        "ease_back_in": ReviewOption(
            "Ease back in", "One short, easy session to get moving again."
        ),
        "rest_more": ReviewOption("Rest a bit more", "Take a few more days off, no pressure."),
        "pick_one_day": ReviewOption("Pick one day", "Choose one day this week for a session."),
        "keep_easy_while_readjusting": ReviewOption(
            "Keep it easy", "Short, easy sessions while your body readjusts."
        ),
        "same_as_this_week": ReviewOption(
            "Same as this week", "Keep the same amount as this week."
        ),
        "rest_when_needed": ReviewOption(
            "Rest when needed", "Take a day off whenever your legs feel heavy."
        ),
        "rest_fully": ReviewOption("Rest fully", "Take a few days off to recover."),
        "go_easy": ReviewOption("Go easy", "Only easy sessions this week."),
        "short_and_light": ReviewOption(
            "Short and light", "Keep sessions short and the effort low."
        ),
        "add_a_bit_more": ReviewOption(
            "Add a bit more", "A little more time, or one harder session."
        ),
        "keep_it_steady": ReviewOption("Keep it steady", "Train the same way as last week."),
        "stay_easy": ReviewOption("Stay easy", "Keep it easy and save your energy."),
        "keep_the_rhythm": ReviewOption("Keep the rhythm", "Train the same way as last week."),
        "go_a_bit_easier": ReviewOption("Go a bit easier", "Lighter sessions for a few days."),
        "add_one_session": ReviewOption("Add one session", "One more easy session this week."),
        "swap_in_easy": ReviewOption(
            "Swap in easy days", "Turn some moderate sessions into easy ones."
        ),
    },
    Language.JA: {
        "keep_easy_while_records": ReviewOption("軽めに続ける", "記録がたまるまで、軽い練習で。"),
        "same_as_usual": ReviewOption("いつもどおり", "今週はふだんどおりに練習する。"),
        "ease_back_in": ReviewOption("少しずつ再開", "短く軽い練習を1回して、体を動かす。"),
        "rest_more": ReviewOption("もう少し休む", "あと数日休んでも大丈夫。"),
        "pick_one_day": ReviewOption("1日決める", "今週、練習する日を1日決める。"),
        "keep_easy_while_readjusting": ReviewOption(
            "軽めに続ける", "体が慣れるまで、短く軽い練習で。"
        ),
        "same_as_this_week": ReviewOption("今週と同じ量", "今週と同じくらいの量を続ける。"),
        "rest_when_needed": ReviewOption("疲れたら休む", "脚が重い日は、遠慮なく休む。"),
        "rest_fully": ReviewOption("しっかり休む", "数日休んで回復する。"),
        "go_easy": ReviewOption("軽めにする", "今週は軽い練習だけにする。"),
        "short_and_light": ReviewOption("短く軽く", "練習は短く、強度は低めに。"),
        "add_a_bit_more": ReviewOption("少し増やす", "時間を少し増やすか、きつめの練習を1回。"),
        "keep_it_steady": ReviewOption("今のペースで", "先週と同じように練習する。"),
        "stay_easy": ReviewOption("軽めにする", "軽めにして、余力を残す。"),
        "keep_the_rhythm": ReviewOption("このリズムで", "先週と同じように練習する。"),
        "go_a_bit_easier": ReviewOption("少し軽めに", "数日は軽めの練習にする。"),
        "add_one_session": ReviewOption("1回足す", "今週、軽い練習を1回増やす。"),
        "swap_in_easy": ReviewOption("軽い日に替える", "中強度の練習の一部を、軽い練習に替える。"),
    },
}


# 量や強度を上げる選択肢。体調のフラグが立った週と、練習の量が多めだった週は外す。
# 外しても 2 個は残る
_ADDS_LOAD = frozenset({"add_a_bit_more", "add_one_session"})

# 中強度寄りの週に出す選択肢。中強度の一部を低強度に置き換える。足す形にしない
# （量が多めの週の「増やさない」とぶつかるため）
_SWAP_IN_EASY = "swap_in_easy"

# 「今と同じ」選択肢。中強度寄りの週は、今の配分を続けることになるので、置き換える選択肢と替える
_SAME_AS_NOW = frozenset(
    {"same_as_usual", "same_as_this_week", "keep_it_steady", "keep_the_rhythm"}
)


@dataclass(frozen=True)
class _EffortLines:
    """練習の量と強度の配分の一言。1 つの言語の分。"""

    hard_went_up: str
    heavy: str
    mostly_moderate: str
    usual: str
    light: str


# 練習の量と強度の配分の一言。入れるのは、疲労・休めている・順調の週だけ（記録が
# 足りない週と中断明けは、その週の事情を話す方を優先する）。言うのは判定で確かめられる
# 事実だけにする。
#
# 高強度・多め・中強度寄りは、助言の向き（控える、なじませる、置き換える）が状況の締めと
# そろうので、締めの 1 文と入れ替えて長さを 15 秒ほどに保つ。
# 高強度は「負荷が普段より多く、高強度の時間も増えた」までしか言わない。判定は増え方の比べ
# だけで、負荷の増えた分の大半が高強度だったとは確かめていないため（過去 1 分・今週 3 分の
# ように、どちらも小さい値でも立つ）。
#
# いつもどおり・少なめは、状況の締め（回復を勧める、増やしてよい、体の声を聞く）を消すと
# 助言とずれるので、締めは残し、その直前に事実だけの短い文を足す。いちばん長い定型
# （34 語）に足しても 40 語に収まる長さにする
_EFFORT_LINES = {
    Language.EN: _EffortLines(
        hard_went_up=(
            "Your load was well above usual, and hard-effort time went up too, "
            "so ease off hard sessions."
        ),
        heavy="You did well above your usual load this week, so let that work sink in.",
        mostly_moderate=(
            "Much of your time was at moderate effort, so swapping some for easy sessions can help."
        ),
        usual="Your load matched your usual weeks.",
        light="Your load was lighter than usual.",
    ),
    Language.JA: _EffortLines(
        hard_went_up="負荷がふだんよりかなり多く、高強度の時間も増えたので、きつい練習は控えめにしましょう。",
        heavy="今週はふだんよりかなり多く練習したので、その分を体になじませましょう。",
        mostly_moderate="中強度の時間が多めだったので、一部を軽い練習に替えるといいですよ。",
        usual="負荷はふだんの週と同じくらいでした。",
        light="負荷はふだんより少なめでした。",
    ),
}


def fallback_review(
    week: WeekSituation,
    health_flag: bool = False,
    effort: Effort = NO_EFFORT,
    language: Language = DEFAULT_LANGUAGE,
) -> ReviewContent:
    """判定した状況から、定型のセリフと選択肢を language で作る。

    health_flag はメモの体調のフラグ。メモを確かめていなければ False のまま呼ぶ。
    effort は練習の量と強度の配分の判定。量が多めの週は、量を増やす選択肢を出さず、
    セリフも増やすことを勧めない言い方にする。中強度寄りの週は、「今と同じ」選択肢を
    中強度を低強度に置き換える選択肢に替える。疲労・休めている・順調の週は、セリフの締めを
    量と配分の一言に入れ替える。
    """
    holds_back = health_flag or effort.volume is Volume.HEAVY
    keys = _OPTIONS[week.situation]
    if holds_back:
        keys = tuple(k for k in keys if k not in _ADDS_LOAD)
    if effort.mostly_moderate:
        keys = _with_swap(keys)
    replacement, fact = _effort_line(effort, _EFFORT_LINES[language])
    script = (_script_ja if language is Language.JA else _script)(
        week, holds_back, replacement, fact
    )
    texts = _OPTION_TEXT[language]
    return ReviewContent(script=script, options=tuple(texts[k] for k in keys))


def _with_swap(keys: tuple[str, ...]) -> tuple[str, ...]:
    """「今と同じ」選択肢を、中強度を低強度に置き換える選択肢に替える。なければ、3 個なら
    最後の 1 個を替え、2 個なら足す。休む・軽く流す選択肢は残す。"""
    same = [i for i, k in enumerate(keys) if k in _SAME_AS_NOW]
    if same:
        i = same[0]
    elif len(keys) >= 3:
        i = len(keys) - 1
    else:
        return (*keys, _SWAP_IN_EASY)
    return (*keys[:i], _SWAP_IN_EASY, *keys[i + 1 :])


def _effort_line(effort: Effort, lines: _EffortLines) -> tuple[str | None, str | None]:
    """量と配分の一言。(締めと入れ替える文, 締めの前に足す文) のどちらか 1 つだけを返す。

    量が多めで高強度の時間も増えた > 多め > 中強度寄り > いつもどおり > 少なめ の順に 1 つ選ぶ。
    何も判定できなければ (None, None)（締めの 1 文をそのまま使う）。
    """
    if effort.hard_went_up:
        return lines.hard_went_up, None
    if effort.volume is Volume.HEAVY:
        return lines.heavy, None
    if effort.mostly_moderate:
        return lines.mostly_moderate, None
    if effort.volume is Volume.USUAL:
        return None, lines.usual
    if effort.volume is Volume.LIGHT:
        return None, lines.light
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
            return (
                "Welcome back! "
                f"You started training again after {_count(_rest_days_before(week), 'day')} off. "
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


def _rest_days_before(week: WeekSituation) -> int:
    # 中断明けは、その週の最初のワークアウトの前の休みから判定するので必ずある。
    # ないのは判定と材料の食い違い。assert は最適化の実行で消えるので使わない
    if week.rest_days_before is None:
        raise ValueError("rest_days_before is required for a returning week")
    return week.rest_days_before


def _script_ja(
    week: WeekSituation,
    holds_back: bool,
    replacement: str | None = None,
    fact: str | None = None,
) -> str:
    """_script の日本語。言うことと、締めの入れ替え方は英語と同じ。数は「3回」「45分」と書く。

    中断明けの日数は、記録のなかった日数（rest_days_before）なので「N日休んで」と言う。
    「N日ぶり」は前の練習の日から数えるので、1 日ずれる。
    """

    def closing(default: str) -> str:
        return "".join(part for part in (fact, replacement or default) if part)

    match week.situation:
        case Situation.NOT_ENOUGH_DATA:
            return _not_enough_data_script_ja(week)
        case Situation.NO_TRAINING:
            return (
                "今週は練習がありませんでしたね。大丈夫です。"
                "忙しい週もありますし、休むのも練習のうちです。"
                "準備ができたら、軽い練習から少しずつ体を動かしましょう。"
            )
        case Situation.RETURNING:
            return (
                f"おかえりなさい！{_rest_days_before(week)}日休んで、練習を再開しましたね。"
                "体力が戻るには少し時間がかかるので、焦らなくて大丈夫です。"
                "軽めに始めて、少しずつ戻していきましょう。"
            )
        case Situation.FATIGUED:
            return (
                "よく頑張っていますね。今は疲労が体力をかなり上回っていて、体が回復を求めています。"
                + closing("軽めの週にすると、これまでの練習が体になじみます。")
            )
        case Situation.FRESH if holds_back:
            return (
                "今は疲労が体力を下回っています。ただ、数字だけでは分からないこともあります。"
                + closing("今週は無理せず、自分のペースで、体の声を聞きながら過ごしましょう。")
            )
        case Situation.FRESH:
            return (
                "しっかり休めていますね。今は疲労が体力を下回っていて、練習する余裕があります。"
                + closing("調子がよければ、少し増やしてみるのにいい時期です。")
            )
        case Situation.STEADY:
            minutes = (week.total_sec + 30) // 60
            return (
                f"安定した週でした。{week.workouts}回、合計{minutes}分の練習で、"
                "体力と疲労のバランスもとれています。"
                + closing("このリズムを続けることが、体力を積み上げる近道です。")
            )


def _not_enough_data_script_ja(week: WeekSituation) -> str:
    """_not_enough_data_script の日本語。"""
    if week.workouts == 0:
        return (
            "まだあなたの練習を知っている途中です。体力を読み取るには、6週間ほどの記録が要ります。"
            "まだ記録がないので、始めたらすぐにもっとお話しできます。"
        )
    if week.unknown_load_days > 0 and week.workouts == 1:
        return (
            "今週は1回練習しましたが、心拍数の記録がないので、体力と疲労をはっきり読み取れません。"
            "毎回心拍数を記録すると、もっとお話しできます。"
        )
    if week.unknown_load_days > 0:
        return (
            f"今週は{week.workouts}回練習しましたが、心拍数のない回があるので、"
            "体力と疲労をはっきり読み取れません。毎回心拍数を記録すると、もっとお話しできます。"
        )
    return (
        f"今週は{week.workouts}回練習しました。体力と疲労を読み取るには、"
        "心拍数つきの記録が数週間分要るので、まだはっきりとは分かりません。"
        "この調子で続けてくださいね。"
    )
