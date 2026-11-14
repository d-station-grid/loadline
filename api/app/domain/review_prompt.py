"""LLM に週次レビューを書いてもらうための指示と材料、返ってきた文の検査。

数字の比較はここ（コード）で済ませ、LLM には結果だけを渡す。状況の判定、前の週との差、
練習の量と強度の配分（effort）、量を増やす選択肢を出してよいかは、どれもコードで決めてから
渡す。出してよいかは、状況、メモの体調のフラグ（note_check）、練習の量から決める。
負荷の比の数値は渡さない（「1.6 倍」のように話させない）。区分だけを渡す。
渡す数字は、定型と同じく回数、分、休んだ日数とその差だけ。体力と疲労の値は渡さない。
今の計算の単位では体力が 20 前後になり、一般的な目安の数字と比べると誤解を招くため。
メモは、呼ぶ側が「メモを AI に送らない」設定を見て、送ってよいものだけを渡す。
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from app.domain.effort import NO_EFFORT, Effort, Volume
from app.domain.fallback_review import ReviewContent, ReviewOption
from app.domain.review_material import ReviewMaterial
from app.domain.situation import Situation

# セリフは声に出して 15 秒ほど
LINE_MIN_WORDS = 28
LINE_MAX_WORDS = 40
MIN_OPTIONS = 2
MAX_OPTIONS = 3
# weekly_review_options の列の長さ
LABEL_MAX_CHARS = 64
DESCRIPTION_MAX_CHARS = 255

# 量や強度を上げる選択肢を出してよい状況。定型と同じ。判定は「疲労」より先に
# 「記録が足りない」「走れなかった週」「中断明け」を当てるので、この 3 つも疲労が高いことがある
_MAY_OFFER_MORE = frozenset({Situation.FRESH, Situation.STEADY})


def may_offer_more(situation: Situation, health_flag: bool, effort: Effort = NO_EFFORT) -> bool:
    """量や強度を上げる選択肢を出してよいか。痛みや病気に触れたメモがある週と、練習の量が
    普段より多めだった週は出さない。"""
    return situation in _MAY_OFFER_MORE and not health_flag and effort.volume is not Volume.HEAVY


SYSTEM_INSTRUCTION = """\
You are a gentle companion who stands beside a training dashboard and talks to an amateur \
cyclist and runner about their past week. Your words are spoken aloud by a text-to-speech \
voice, so write the way a warm friend talks: short sentences, plain words, no lists, no emoji, \
no markdown.

How you talk:
- Encouragement first. Notice what the person did, and what life threw at them. Never blame, \
never shame, never compare them to others.
- `situation` was decided by our own code from the numbers. Trust it and never contradict it.
  - not_enough_data: the records are too short, or some sessions have no heart rate, so \
fitness and fatigue cannot be read yet.
  - no_training: there were no sessions this week.
  - returning: they started training again this week after a break.
  - fatigued: fatigue is well above fitness.
  - fresh: fatigue is below fitness, so there is room to train.
  - steady: fitness and fatigue are in balance.
- Use only numbers that appear in the input, and mention at most two. Never calculate new \
numbers and never give fitness or fatigue as a number.
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
  - `hard_efforts_jumped`: true means the load was clearly above usual and time at hard \
effort also went up. It does not tell how much of the extra load came from hard efforts, so \
never say the increase came mainly from them. Suggest going easy on hard sessions for now.
- `last_choice` is the option they picked for this week, if any. You may mention it kindly, \
but do not judge whether they followed it.
- You never give orders and never hand out a fixed plan. You offer two or three options and \
let the person choose. One option must always be the gentle one (rest or easy). When \
`may_offer_more` is false, or the notes mention pain or sickness, do not suggest raising \
intensity, volume or the number of sessions, either in `line` or in any option.
- You are not a doctor. Do not diagnose, do not name medicines or treatments, do not say a \
symptom is nothing to worry about. If pain or sickness keeps coming up, you may suggest \
seeing a doctor, once, softly.
- Do not use the terms TSS, CTL, ATL, TSB, PMC or TRIMP. Say fitness, fatigue and reserve.

Write `line` and the options in English, even when the notes are in another language.

Length: only `line` is spoken aloud, and it must take about 15 seconds to say: 28 to 40 \
words. Do not end `line` with a question that hands the choice back (no "How would you like \
to...?"); the buttons already do that. The options are shown as buttons and are not spoken: \
`label` is 2 to 4 words, and `description` is one short sentence of at most 14 words."""


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
            "hard_efforts_jumped": effort.hard_spike,
        },
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
        "code; trust them. Write what you say today, and the options.\n\n"
        + json.dumps(data, ensure_ascii=False, indent=1)
    )


def check_review(content: ReviewContent) -> ReviewContent:
    """長さと数を確かめ、前後の空白を落として返す。合わなければ InvalidReviewError。

    中身が安全かどうかは、ここでは見ない（別の確認に任せる）。
    """
    script = " ".join(content.script.split())
    words = len(script.split())
    if not LINE_MIN_WORDS <= words <= LINE_MAX_WORDS:
        raise InvalidReviewError(f"line must be {LINE_MIN_WORDS}-{LINE_MAX_WORDS} words: {words}")
    if not MIN_OPTIONS <= len(content.options) <= MAX_OPTIONS:
        raise InvalidReviewError(
            f"options must be {MIN_OPTIONS}-{MAX_OPTIONS}: {len(content.options)}"
        )
    options = tuple(ReviewOption(o.label.strip(), o.description.strip()) for o in content.options)
    for o in options:
        if not 0 < len(o.label) <= LABEL_MAX_CHARS:
            raise InvalidReviewError(f"label must be 1-{LABEL_MAX_CHARS} chars: {o.label!r}")
        if not 0 < len(o.description) <= DESCRIPTION_MAX_CHARS:
            raise InvalidReviewError(
                f"description must be 1-{DESCRIPTION_MAX_CHARS} chars: {o.description!r}"
            )
    return ReviewContent(script=script, options=options)


def _minutes(sec: int) -> int:
    """秒を分に四捨五入する。負の差も 0 から遠い側に丸める。定型の分と同じ丸め方。

    round は偶数への丸め（150.5 → 150）なので、30 秒を足して切り捨てる。
    """
    sign = -1 if sec < 0 else 1
    return sign * ((abs(sec) + 30) // 60)
