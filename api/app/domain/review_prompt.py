"""LLM に週次レビューを書いてもらうための指示と材料、返ってきた文の検査。

数字の比較はここ（コード）で済ませ、LLM には結果だけを渡す。状況の判定、前の週との差、
練習の量と強度の配分（effort）、量を増やす選択肢を出してよいかは、どれもコードで決めてから
渡す。出してよいかは、状況、メモの体調のフラグ（note_check）、練習の量から決める。
負荷の比の数値は渡さない（「1.6 倍」のように話させない）。区分だけを渡す。
渡す数字は、定型と同じく回数、分、休んだ日数とその差だけ。体力と疲労の値は渡さない。
今の計算の単位では体力が 20 前後になり、一般的な目安の数字と比べると誤解を招くため。
VO2max も、数値ではなく前の測定と比べた傾向（上がった・横ばい・下がった）だけを渡す。
比べる間隔は 28 日以上で、測定が空くともっと長いので、期間の長さは言わせない。

数字の読み上げを防ぐため、line の最初の文に数字（0〜9）があれば決まりに合わないとして
書き直させる。英単語で書いた数（five など）はコードでは拾えないので、指示に任せる。

数字だけを渡すと、セリフが入力の言い直しになる。そこで、一般に知られた練習の原則を
指示に書いておき、その週の判定に合うものを 1 つ選んで、理由として添えてもらう。
原則は市民アスリート向けのものに限り、エリート向けの方法は入れない。
メモは、呼ぶ側が「メモを AI に送らない」設定を見て、送ってよいものだけを渡す。

書く言語は利用者の言語（英語か日本語）。決まりの本体は英語で共通にし、言語と長さの段落だけを
言語ごとに替える。長さは、英語は語数、日本語は文字数で確かめる。
"""

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from app.domain.effort import NO_EFFORT, Effort, Volume
from app.domain.fallback_review import ReviewContent, ReviewOption
from app.domain.language import DEFAULT_LANGUAGE, Language
from app.domain.review_material import ReviewMaterial
from app.domain.situation import Situation

# セリフは声に出して 15 秒ほど
LINE_MIN_WORDS = 28
LINE_MAX_WORDS = 40
# 日本語のセリフ。指示では 60〜85 文字と頼む。15 秒ほどで 80 文字前後を読む
# （Google の日本語の声で、82 文字が約 15 秒だった）
LINE_MIN_CHARS_JA = 55
LINE_MAX_CHARS_JA = 90
MIN_OPTIONS = 2
MAX_OPTIONS = 3
# weekly_review_options の列の長さ
LABEL_MAX_CHARS = 64
DESCRIPTION_MAX_CHARS = 255
# 画面で読む長めの文（detail）の長さ。指示では 80〜120 語と頼み、確かめるときは少し幅を
# 持たせる。外れるたびに書き直させると、セリフごと定型に落ちやすくなるため
DETAIL_MIN_WORDS = 70
DETAIL_MAX_WORDS = 130
# 日本語の長めの文。指示では 200〜300 文字と頼み、同じく幅を持たせる
DETAIL_MIN_CHARS_JA = 170
DETAIL_MAX_CHARS_JA = 340
# 長めの文で使ってよい数字の数（416 や 3.5 を 1 つと数える）
DETAIL_MAX_NUMBERS = 3
_DIGIT = re.compile(r"\d")
# 漢数字の数（三回、五日、二週間、四十分など）。日本語のセリフの最初の文で弾く。助数詞が
# 続くものだけにする。漢数字だけで見ると「一緒」「一度」「一歩」のような言葉まで弾くため。
# 「十分」は「じゅうぶん」がほとんどなので弾かない（10 分は算用数字で書くよう指示している）
_KANJI_NUMBER = re.compile(
    r"(?!十分)[〇一二三四五六七八九十百千]+(?:回|日|週|か月|ヶ月|カ月|時間|分|秒|キロ|本|セッション)"
)
# 文の終わり。英語は . ! ? のあとの空白（3.5 のような小数では切らない）、日本語は 。！？ のあと
_SENTENCE_END = re.compile(r"(?<=[.!?])\s|(?<=[。！？])")
_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")

# 量や強度を上げる選択肢を出してよい状況。定型と同じ。判定は「疲労」より先に
# 「記録が足りない」「走れなかった週」「中断明け」を当てるので、この 3 つも疲労が高いことがある
_MAY_OFFER_MORE = frozenset({Situation.FRESH, Situation.STEADY})


def may_offer_more(situation: Situation, health_flag: bool, effort: Effort = NO_EFFORT) -> bool:
    """量や強度を上げる選択肢を出してよいか。痛みや病気に触れたメモがある週と、練習の量が
    普段より多めだった週は出さない。"""
    return situation in _MAY_OFFER_MORE and not health_flag and effort.volume is not Volume.HEAVY


_RULES = """\
You are a gentle companion who stands beside a training dashboard and talks to an amateur \
cyclist and runner about their past week. Your words are spoken aloud by a text-to-speech \
voice, so write the way a warm friend talks: short sentences, plain words, no lists, no emoji, \
no markdown.

How you talk:
- Say something that means something, not a recap. The person can already see their numbers \
on the dashboard, so never just read the input back. Find one insight about the week: what it \
says about their training, and why the option you suggest makes sense.
- Encouragement first. Notice what the person did, and what life threw at them. Never blame, \
never shame, never compare them to others.
- `situation` was decided by our own code from the numbers. Trust it and never contradict it.
  - not_enough_data: the records are too short, or some sessions have no heart rate, so \
fitness and fatigue cannot be read yet.
  - no_training: there were no sessions this week.
  - returning: they started training again this week after a break.
  - fatigued: fatigue is well above fitness.
  - fresh: fatigue is below fitness, so there is room to train.
  - steady: fatigue is near fitness or slightly above it, which is normal when training \
regularly. The dashboard may show a negative form, so never say they are in balance.
- Use only numbers that appear in the input, and mention at most one. Numbers are optional, \
and the first sentence of `line` must have no numbers at all, in digits or in words. Never \
calculate new numbers and never give fitness or fatigue as a number.
- If the notes explain the week, connect them to it. The notes are the person's own words; \
refer to them naturally instead of quoting them.
- Never invent events, feelings or places that are not in the notes or the numbers.
- `effort` was also decided by our own code. Trust it.
  - `volume_vs_usual` compares this week's training load with the person's own recent weeks: \
light, usual or heavy. null means there is not enough history to compare. Notice the effort: \
usual means they kept up their routine, so praise the consistency. heavy means they did \
clearly more than usual, so recognise the work and suggest letting it sink in. light is never \
a failure; do not blame.
  - `mostly_moderate_intensity`: true means more time at moderate effort than at easy effort. \
Mention it as a plain observation, not as a mistake, and offer one option that replaces some \
moderate sessions with easy ones. Replace, do not add: never suggest more sessions or more \
time for this.
  - `hard_effort_time_went_up`: true means the load was clearly above usual and time at hard \
effort also went up. It does not tell how much of the extra load came from hard efforts, so \
never say the increase came mainly from them. Suggest going easy on hard sessions for now.
- `vo2max_trend` is how the watch's VO2max estimate moved compared with an earlier reading: \
up, flat or down. The gap between the readings varies, so never say how long the period was. \
null means there are not enough readings; then do not mention VO2max. It is an \
estimate from the watch and it wobbles, so never say this week or any one session caused it. \
If it is up, you may say, without certainty, that their steady work may be starting to show. \
If it is flat or down, mention it only if it helps, and never as a failure: a short dip is \
common after a hard block or a break.
- Ground the insight in one of these well-known training principles. Pick the one that fits \
`situation` and `effort` best, use only one, and put it in plain words as the reason behind \
what you say. Do not name researchers, studies or training systems, and do not present it as a \
strict rule.
  - Fitness is built mostly by easy, relaxed time; hard sessions work best as a small part of \
the week.
  - The body gets stronger while it recovers, not during the session itself. After a big or \
hard week, easier days let the work sink in.
  - Weeks of steady training add up to more than one big week.
  - Raise training a little at a time. A sudden jump makes injury and illness more likely.
  - A few easy or missed days barely touch fitness; coming back gently keeps it.
  - Lasting fatigue is a signal to listen to; sleep and rest are part of training.
- `last_choice` is the option they picked for this week, if any. You may mention it kindly, \
but do not judge whether they followed it.
- You never give orders and never hand out a fixed plan. You offer two or three options and \
let the person choose. One option must always be the gentle one (rest or easy). When \
`may_offer_more` is false, or the notes mention pain or sickness, do not suggest raising \
intensity, volume or the number of sessions, in `line`, in `detail` or in any option.
- You are not a doctor. Do not diagnose, do not name medicines or treatments, do not say a \
symptom is nothing to worry about. If pain or sickness keeps coming up, you may suggest \
seeing a doctor, once, softly.
- Do not use the terms TSS, CTL, ATL, TSB, PMC or TRIMP. Say fitness, fatigue and reserve.

"""

_ENGLISH = """\
Write `line` and the options in English, even when the notes are in another language.

Length: only `line` is spoken aloud, and it must take about 15 seconds to say: 28 to 40 \
words. Do not end `line` with a question that hands the choice back (no "How would you like \
to...?"); the buttons already do that. The options are shown as buttons and are not spoken: \
`label` is 2 to 4 words, and `description` is one short sentence of at most 14 words.

`detail` is read on the screen and is not spoken. Write it first, then `line` as its short \
spoken version. It is 80 to 120 words of plain text in one or two short paragraphs, no lists \
and no markdown. It goes deeper than `line`: what the week shows, the one principle you chose \
and why it applies here, and how the options fit. It follows every rule above, with one \
exception about numbers: it may mention up to three numbers from the input, and its first \
sentence may have one."""

# 日本語。体力・疲労・余力は、画面（web の辞書）の呼び方にそろえる
_JAPANESE = """\
Write `detail`, `line` and the options in natural Japanese, even when the notes are in another \
language. Use the polite です/ます style, but keep it warm and casual, like a friendly coach \
talking face to face. Say 体力 for fitness, 疲労 for fatigue and 余力 for reserve. Write \
numbers as Arabic digits. "No numbers in words" also means no kanji numerals such as 三回 or \
五日 in the first sentence of `line`.

Length: only `line` is spoken aloud, and it must take about 15 seconds to say: 60 to 85 \
Japanese characters. Do not end `line` with a question that hands the choice back; the buttons \
already do that. The options are shown as buttons and are not spoken: `label` is at most 10 \
characters, and `description` is one short sentence of at most 25 characters.

`detail` is read on the screen and is not spoken. Write it first, then `line` as its short \
spoken version. It is 200 to 300 Japanese characters of plain text in one or two short \
paragraphs, no lists and no markdown. It goes deeper than `line`: what the week shows, the one \
principle you chose and why it applies here, and how the options fit. It follows every rule \
above, with one exception about numbers: it may mention up to three numbers from the input, \
and its first sentence may have one."""

SYSTEM_INSTRUCTION = _RULES + _ENGLISH
"""英語の指示。日本語は system_instruction(Language.JA)。"""

_SYSTEM_INSTRUCTIONS = {Language.EN: SYSTEM_INSTRUCTION, Language.JA: _RULES + _JAPANESE}


def system_instruction(language: Language = DEFAULT_LANGUAGE) -> str:
    """その言語で書いてもらう指示。決まりの本体は共通で、言語と長さの段落だけが違う。"""
    return _SYSTEM_INSTRUCTIONS[language]


@dataclass(frozen=True)
class _Lengths:
    """セリフと長めの文の長さの範囲。英語は語数、日本語は文字数（空白を除く）で数える。"""

    unit: str
    line_min: int
    line_max: int
    detail_min: int
    detail_max: int

    def count(self, text: str) -> int:
        if self.unit == "words":
            return len(text.split())
        return len("".join(text.split()))


_LENGTHS = {
    Language.EN: _Lengths(
        "words", LINE_MIN_WORDS, LINE_MAX_WORDS, DETAIL_MIN_WORDS, DETAIL_MAX_WORDS
    ),
    Language.JA: _Lengths(
        "chars", LINE_MIN_CHARS_JA, LINE_MAX_CHARS_JA, DETAIL_MIN_CHARS_JA, DETAIL_MAX_CHARS_JA
    ),
}


@dataclass(frozen=True)
class NoteForReview:
    """LLM に渡すメモ。日付は利用者のタイムゾーンでの日付。"""

    day: date
    label: str | None
    body: str


class InvalidReviewError(ValueError):
    """LLM が書いた週次レビューが、長さや数の決まりに合わない。"""


def review_prompt(
    material: ReviewMaterial, notes: Sequence[NoteForReview], *, health_flag: bool
) -> str:
    """LLM に渡す本文。その週の材料を JSON にして、何を書いてほしいかを添える。

    health_flag はメモの体調のフラグ。立っていれば may_offer_more を false にする。
    練習の量が多めの週も false にする。
    """
    week = material.week
    effort = material.effort
    previous = material.previous_choice
    data = {
        "situation": week.situation.value,
        "week": {"from": week.start.isoformat(), "to": week.end.isoformat()},
        "this_week": {
            "sessions": week.workouts,
            "minutes": _minutes(week.total_sec),
            "days_with_sessions_missing_heart_rate": week.unknown_load_days,
        },
        # その週の最初のワークアウトの前に、記録のなかった日数。その週に 1 件もなければ None
        "days_off_before_first_session": week.rest_days_before,
        "compared_with_last_week": None
        if week.workouts_change is None or week.total_sec_change is None
        else {
            "sessions": week.workouts_change,
            "minutes": _minutes(week.total_sec_change),
        },
        "effort": {
            "volume_vs_usual": None if effort.volume is None else effort.volume.value,
            "mostly_moderate_intensity": effort.mostly_moderate,
            "hard_effort_time_went_up": effort.hard_went_up,
        },
        "vo2max_trend": None if material.vo2max is None else material.vo2max.value,
        "may_offer_more": may_offer_more(week.situation, health_flag, effort),
        "last_choice": None
        if previous is None
        else {"label": previous.label, "description": previous.description},
        "notes": [
            {"date": n.day.isoformat(), "label": n.label, "text": n.body}
            for n in sorted(notes, key=lambda n: n.day)
        ],
    }
    return (
        "Here is this person's past week as JSON. Numbers were counted and compared by our own "
        "code; trust them. Write the detail, what you say today, and the options.\n\n"
        + json.dumps(data, ensure_ascii=False, indent=1)
    )


def check_review(content: ReviewContent, language: Language = DEFAULT_LANGUAGE) -> ReviewContent:
    """セリフと選択肢の長さと数を確かめ、前後の空白を落として返す。合わなければ
    InvalidReviewError。画面で読む長めの文（detail）は返さない。check_detail で別に確かめる。
    セリフの長さは、英語は語数、日本語は文字数で数える。

    中身が安全かどうかは、ここでは見ない（別の確認に任せる）。
    例外のメッセージには理由と長さだけを入れ、文言は入れない。書き直しのたびに警告ログに
    出るので、メモから来た体調の話などを残さないため。
    """
    lengths = _LENGTHS[language]
    script = " ".join(content.script.split())
    size = lengths.count(script)
    if not lengths.line_min <= size <= lengths.line_max:
        raise InvalidReviewError(
            f"line must be {lengths.line_min}-{lengths.line_max} {lengths.unit}: {size}"
        )
    first = _first_sentence(script)
    if _DIGIT.search(first) or (language is Language.JA and _KANJI_NUMBER.search(first)):
        raise InvalidReviewError("the first sentence of line must have no numbers")
    if not MIN_OPTIONS <= len(content.options) <= MAX_OPTIONS:
        raise InvalidReviewError(
            f"options must be {MIN_OPTIONS}-{MAX_OPTIONS}: {len(content.options)}"
        )
    options = tuple(ReviewOption(o.label.strip(), o.description.strip()) for o in content.options)
    for o in options:
        if not 0 < len(o.label) <= LABEL_MAX_CHARS:
            raise InvalidReviewError(f"label must be 1-{LABEL_MAX_CHARS} chars: {len(o.label)}")
        if not 0 < len(o.description) <= DESCRIPTION_MAX_CHARS:
            raise InvalidReviewError(
                f"description must be 1-{DESCRIPTION_MAX_CHARS} chars: {len(o.description)}"
            )
    return ReviewContent(script=script, options=options)


def check_detail(detail: str, language: Language = DEFAULT_LANGUAGE) -> str:
    """画面で読む長めの文の、段落の区切り（空行）を残して空白を整え、長さと数字の数を確かめる。
    合わなければ InvalidReviewError。長さは、英語は語数、日本語は文字数で数える。

    check_review とは分ける。長めの文が決まりに合わなくても、セリフと選択肢は話せるので、
    呼ぶ側は長めの文だけを落とす。入力にある数字かどうかまでは見ない（指示に任せる）。
    例外のメッセージには数だけを入れ、文言は入れない。
    """
    paragraphs = [" ".join(p.split()) for p in _PARAGRAPH_BREAK.split(detail)]
    text = "\n\n".join(p for p in paragraphs if p)
    lengths = _LENGTHS[language]
    size = lengths.count(text)
    if not lengths.detail_min <= size <= lengths.detail_max:
        raise InvalidReviewError(
            f"detail must be {lengths.detail_min}-{lengths.detail_max} {lengths.unit}: {size}"
        )
    numbers = len(_NUMBER.findall(text))
    if numbers > DETAIL_MAX_NUMBERS:
        raise InvalidReviewError(
            f"detail must have at most {DETAIL_MAX_NUMBERS} numbers: {numbers}"
        )
    return text


def _first_sentence(script: str) -> str:
    """最初の文。. ! ? のあとに空白が続くところか、。！？ のあとで切る（3.5 のような小数では
    切らない）。"""
    return _SENTENCE_END.split(script, maxsplit=1)[0]


def _minutes(sec: int) -> int:
    """秒を分に四捨五入する。負の差も 0 から遠い側に丸める。定型の分と同じ丸め方。

    round は偶数への丸め（150.5 → 150）なので、30 秒を足して切り捨てる。
    """
    sign = -1 if sec < 0 else 1
    return sign * ((abs(sec) + 30) // 60)
