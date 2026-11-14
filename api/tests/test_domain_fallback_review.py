from dataclasses import replace
from datetime import date, timedelta

import pytest

from app.domain.effort import Effort, PastWeek, Volume, judge_effort
from app.domain.fallback_review import fallback_review
from app.domain.load import FitnessPoint, ZoneTimes
from app.domain.situation import Situation, WeekInput, WeekSituation, judge_week

MONDAY = date(2026, 9, 28)

BASE = WeekSituation(
    situation=Situation.STEADY,
    start=MONDAY,
    end=MONDAY + timedelta(days=6),
    fitness=20.0,
    fatigue=22.0,
    headroom=-2.0,
    headroom_ratio=-0.1,
    workouts=3,
    total_sec=9000,
    unknown_load_days=0,
    rest_days_before=1,
    workouts_change=0,
    total_sec_change=0,
    fitness_change=0.5,
    fatigue_change=0.5,
)


def week(situation: Situation, **changes: object) -> WeekSituation:
    return replace(BASE, situation=situation, **changes)  # type: ignore[arg-type]


def words(text: str) -> int:
    return len(text.split())


# 判定が「疲労」より先に当てる状況と「疲労」。どれも疲労が高いことがある
MAY_BE_TIRED = [
    Situation.NOT_ENOUGH_DATA,
    Situation.NO_TRAINING,
    Situation.RETURNING,
    Situation.FATIGUED,
]
ADDS_LOAD = ("add", "more time", "harder", "push", "extra", "one more")

# 記録が足りない週の 3 つの言い方: 記録がない、心拍のない日がある、記録が短いか体力が 0
NOT_ENOUGH_DATA_WEEKS = [
    pytest.param({"workouts": 0}, id="no_sessions"),
    pytest.param({"workouts": 1, "unknown_load_days": 1}, id="one_session_missing_heart_rate"),
    pytest.param({"unknown_load_days": 1}, id="missing_heart_rate"),
    pytest.param({}, id="short_history"),
]


def adds_load(review_text: str) -> list[str]:
    return [w for w in ADDS_LOAD if w in review_text.lower()]


@pytest.mark.parametrize("situation", list(Situation))
def test_every_situation_has_a_script_of_about_15_seconds(situation: Situation) -> None:
    """声に出して 15 秒ほど。試作のプロンプトと同じ 28〜40 語。"""
    review = fallback_review(week(situation, rest_days_before=20))

    assert 28 <= words(review.script) <= 40


@pytest.mark.parametrize("situation", list(Situation))
def test_every_situation_has_two_or_three_short_options(situation: Situation) -> None:
    """ボタンは 2〜4 語、その下の説明は 14 語まで。同じ週次レビューに同じ文字のボタンを並べない。"""
    options = fallback_review(week(situation, rest_days_before=20)).options

    assert 2 <= len(options) <= 3
    assert all(2 <= words(o.label) <= 4 for o in options)
    assert all(words(o.description) <= 14 for o in options)
    assert len({o.label for o in options}) == len(options)


@pytest.mark.parametrize("situation", list(Situation))
def test_scripts_do_not_use_jargon_or_raw_load_values(situation: Situation) -> None:
    """専門用語を使わず、体力と疲労の値も読み上げない。"""
    review = fallback_review(week(situation, fitness=19.6, fatigue=27.4, rest_days_before=16))
    text = " ".join([review.script, *(f"{o.label} {o.description}" for o in review.options)])

    for term in ("TSS", "CTL", "ATL", "TSB", "PMC", "TRIMP"):
        assert term not in text
    for value in ("19", "27"):
        assert value not in text


@pytest.mark.parametrize("situation", list(Situation))
def test_every_situation_offers_a_gentle_option(situation: Situation) -> None:
    """どの週にも、休むか軽く流す選択肢がある。"""
    labels = {o.label for o in fallback_review(week(situation, rest_days_before=20)).options}

    gentle = {
        "Keep it easy",
        "Rest a bit more",
        "Rest when needed",
        "Rest fully",
        "Go easy",
        "Stay easy",
        "Go a bit easier",
    }
    assert labels & gentle


@pytest.mark.parametrize("situation", MAY_BE_TIRED)
def test_tired_weeks_offer_nothing_that_adds_load(situation: Situation) -> None:
    """疲労が高い週には、強度や量を上げる選択肢を出さない。余力 ÷ 体力 が −75% の週で見る。"""
    tired = week(
        situation,
        fitness=20.0,
        fatigue=35.0,
        headroom=-15.0,
        headroom_ratio=-0.75,
        rest_days_before=14,
    )
    options = fallback_review(tired).options

    assert adds_load(" ".join(f"{o.label} {o.description}" for o in options)) == []


def test_returning_after_a_break_with_high_fatigue_offers_nothing_that_adds_load() -> None:
    """14 日休んで再開し、週末に体力 20・疲労 35。判定は疲労より中断明けを先に当てる。"""
    sunday = MONDAY + timedelta(days=6)
    situation = judge_week(
        WeekInput(
            start=MONDAY,
            first_workout_day=date(2026, 6, 1),
            last_workout_day_before=MONDAY - timedelta(days=15),
            workout_days=[MONDAY, MONDAY + timedelta(days=2), MONDAY + timedelta(days=4)],
            total_sec=10800,
            unknown_load_days=0,
            end=FitnessPoint(day=sunday, load=0.0, fitness=20.0, fatigue=35.0, headroom=-15.0),
            previous=None,
        )
    )
    assert situation.situation == Situation.RETURNING
    assert situation.rest_days_before == 14

    options = fallback_review(situation).options

    assert adds_load(" ".join(f"{o.label} {o.description}" for o in options)) == []


def test_steady_week_says_the_count_and_minutes() -> None:
    """回数と合計の分は、コードで数えた値をそのまま入れる。分は四捨五入。"""
    script = fallback_review(week(Situation.STEADY, workouts=3, total_sec=9030)).script

    assert "You did 3 sessions in 151 minutes" in script


def test_steady_week_with_one_session_uses_the_singular() -> None:
    script = fallback_review(week(Situation.STEADY, workouts=1, total_sec=60)).script

    assert "You did 1 session in 1 minute," in script


def test_returning_week_says_how_many_days_off() -> None:
    script = fallback_review(week(Situation.RETURNING, rest_days_before=16)).script

    assert "after 16 days off" in script


def test_returning_week_without_rest_days_is_a_bug() -> None:
    """中断明けなのに休んだ日数がないのは、判定と材料の食い違い。「None days」とは話さない。"""
    with pytest.raises(ValueError, match="rest_days_before"):
        fallback_review(week(Situation.RETURNING, rest_days_before=None))


@pytest.mark.parametrize("changes", NOT_ENOUGH_DATA_WEEKS)
def test_not_enough_data_scripts_are_about_15_seconds(changes: dict[str, int]) -> None:
    script = fallback_review(week(Situation.NOT_ENOUGH_DATA, **changes)).script

    assert 28 <= words(script) <= 40


def test_not_enough_data_before_the_first_session() -> None:
    """まだ 1 件も記録がないときに「0 sessions」とは言わない。"""
    script = fallback_review(week(Situation.NOT_ENOUGH_DATA, workouts=0)).script

    assert script == (
        "I'm still getting to know your training. "
        "Fitness takes about six weeks of records to read well. "
        "There are no sessions in yet. Once you start, I'll have more to tell you soon."
    )


def test_not_enough_data_with_one_session_missing_heart_rate() -> None:
    """心拍のない 1 回だけの週。「some of them」とは言わず、「6 週間分ない」とも言わない。"""
    script = fallback_review(
        week(Situation.NOT_ENOUGH_DATA, workouts=1, unknown_load_days=1)
    ).script

    assert script == (
        "This week you did 1 session, but it has no heart rate, "
        "so I can't read your fitness and fatigue clearly. "
        "With heart rate on every session, I'll have more to tell you."
    )


def test_not_enough_data_with_sessions_missing_heart_rate() -> None:
    """心拍のない日がある 2 回以上の週。「6 週間分ない」とは言わない。"""
    script = fallback_review(
        week(Situation.NOT_ENOUGH_DATA, workouts=2, unknown_load_days=1)
    ).script

    assert script == (
        "This week you did 2 sessions, but some of them have no heart rate, "
        "so I can't read your fitness and fatigue clearly. "
        "With heart rate on every session, I'll have more to tell you."
    )


def test_not_enough_data_with_a_short_history_says_the_count() -> None:
    """記録が短いか体力が 0。判定の結果からはどちらか分からないので、どちらでも本当の言い方。"""
    script = fallback_review(week(Situation.NOT_ENOUGH_DATA, workouts=2)).script

    assert script.startswith("This week you did 2 sessions. I can't read your fitness")
    assert "six weeks" not in script
    assert "no heart rate" not in script


def test_scripts_do_not_overstate_what_the_numbers_show() -> None:
    """休んだ週に回復したとは、休めている週に疲労が下がったとは、言い切らない。"""
    no_training = fallback_review(week(Situation.NO_TRAINING, workouts=0)).script
    fresh = fallback_review(week(Situation.FRESH)).script

    assert "recover" not in no_training
    assert "dropped" not in fresh


@pytest.mark.parametrize("situation", list(Situation))
def test_health_flag_removes_options_that_add_load(situation: Situation) -> None:
    """痛みや病気に触れたメモがある週は、休めている週や順調な週でも増やす選択肢を外す。
    外しても、軽い選択肢を含めて 2 個は残る。"""
    options = fallback_review(week(situation, rest_days_before=20), health_flag=True).options

    assert adds_load(" ".join(f"{o.label} {o.description}" for o in options)) == []
    assert len(options) >= 2


@pytest.mark.parametrize("situation", list(Situation))
def test_health_flag_keeps_the_script_from_suggesting_more(situation: Situation) -> None:
    """フラグが立った週は、セリフでも増やすことを勧めない。長さは 15 秒ほどのまま。"""
    script = fallback_review(week(situation, rest_days_before=20), health_flag=True).script

    assert adds_load(script) == []
    assert "room to train" not in script


def test_fresh_week_with_the_health_flag_does_not_say_the_body_has_recovered() -> None:
    """痛みや病気がある週か、メモを確かめられなかった週なので、休めた、回復したとは
    言い切らない。疲労が体力より低いという、数字が示すことだけを言う。"""
    script = fallback_review(week(Situation.FRESH), health_flag=True).script

    assert "recover" not in script
    assert "rested" not in script
    assert "fatigue is below your fitness" in script
    assert 28 <= words(script) <= 40


def test_fresh_week_without_the_health_flag_suggests_a_little_more() -> None:
    script = fallback_review(week(Situation.FRESH)).script

    assert adds_load(script) != []


@pytest.mark.parametrize("situation", [Situation.FRESH, Situation.STEADY])
def test_without_the_health_flag_rested_weeks_may_add_load(situation: Situation) -> None:
    """フラグが立っていなければ、休めている週と順調な週には増やす選択肢を 1 つ置く。"""
    options = fallback_review(week(situation)).options

    assert adds_load(" ".join(f"{o.label} {o.description}" for o in options)) != []


HEAVY = Effort(volume=Volume.HEAVY, load_ratio=1.6, mostly_moderate=False, hard_spike=False)


@pytest.mark.parametrize("situation", list(Situation))
def test_heavy_week_removes_options_that_add_load(situation: Situation) -> None:
    """普段より多めに練習した週は、休めている週や順調な週でも増やす選択肢を外す。"""
    review = fallback_review(week(situation, rest_days_before=20), effort=HEAVY)

    assert adds_load(" ".join(f"{o.label} {o.description}" for o in review.options)) == []
    assert len(review.options) >= 2
    assert adds_load(review.script) == []


@pytest.mark.parametrize("volume", [Volume.LIGHT, Volume.USUAL, None])
def test_other_volumes_still_let_the_fresh_week_add_load(volume: Volume | None) -> None:
    """量が多めでなければ、休めている週の選択肢は変えない（増やす選択肢を残す）。"""
    effort = Effort(volume=volume, load_ratio=None, mostly_moderate=False, hard_spike=False)

    assert (
        fallback_review(week(Situation.FRESH), effort=effort).options
        == fallback_review(week(Situation.FRESH)).options
    )


def effort(
    volume: Volume | None = None, mostly_moderate: bool = False, hard_spike: bool = False
) -> Effort:
    return Effort(
        volume=volume, load_ratio=None, mostly_moderate=mostly_moderate, hard_spike=hard_spike
    )


# 量と配分の一言を入れる週
SPOKEN = [Situation.FATIGUED, Situation.FRESH, Situation.STEADY]
EFFORTS = [
    pytest.param(effort(Volume.LIGHT), id="light"),
    pytest.param(effort(Volume.USUAL), id="usual"),
    pytest.param(effort(Volume.HEAVY), id="heavy"),
    pytest.param(effort(Volume.HEAVY, hard_spike=True), id="hard_spike"),
    pytest.param(effort(Volume.USUAL, mostly_moderate=True), id="mostly_moderate"),
    pytest.param(effort(Volume.HEAVY, True, True), id="all"),
]


@pytest.mark.parametrize("situation", list(Situation))
@pytest.mark.parametrize("health_flag", [False, True])
@pytest.mark.parametrize("e", EFFORTS)
def test_effort_keeps_the_script_and_options_short(
    situation: Situation, health_flag: bool, e: Effort
) -> None:
    """一言は締めの 1 文と入れ替えるので、どの組み合わせでも 15 秒ほど（28〜40 語）のまま。
    選択肢も 2〜3 個で、休むか軽く流す選択肢を残す。"""
    review = fallback_review(week(situation, rest_days_before=20), health_flag, e)

    assert 28 <= words(review.script) <= 40
    assert 2 <= len(review.options) <= 3
    assert len({o.label for o in review.options}) == len(review.options)
    labels = {o.label for o in review.options}
    assert labels & {
        "Keep it easy",
        "Rest a bit more",
        "Rest when needed",
        "Rest fully",
        "Go easy",
        "Stay easy",
        "Go a bit easier",
        "Swap in easy days",
    }


@pytest.mark.parametrize("situation", SPOKEN)
@pytest.mark.parametrize(
    ("e", "said"),
    [
        (effort(Volume.LIGHT), "Your load was lighter than usual."),
        (effort(Volume.USUAL), "Your load matched your usual weeks."),
        (effort(Volume.HEAVY), "well above your usual load"),
        (effort(Volume.HEAVY, hard_spike=True), "hard-effort time went up too"),
        (effort(Volume.USUAL, mostly_moderate=True), "moderate effort"),
    ],
)
def test_tired_rested_and_steady_weeks_say_the_effort(
    situation: Situation, e: Effort, said: str
) -> None:
    assert said in fallback_review(week(situation), effort=e).script


def test_the_effort_line_says_one_thing_by_priority() -> None:
    """高強度で急に増えた > 多め > 中強度寄り > いつもどおり の順に 1 つだけ言う。"""
    script = fallback_review(week(Situation.STEADY), effort=effort(Volume.HEAVY, True, True)).script

    assert "hard-effort time went up too" in script
    assert "moderate effort" not in script
    assert "well above your usual load" not in script


@pytest.mark.parametrize("situation", [Situation.RETURNING, Situation.NOT_ENOUGH_DATA])
def test_returning_and_short_history_weeks_keep_their_own_script(situation: Situation) -> None:
    """中断明けと記録が足りない週は、その週の事情を話す方を優先し、一言は入れない。"""
    base = week(situation, rest_days_before=20)

    assert fallback_review(base, effort=effort(Volume.USUAL)).script == fallback_review(base).script


@pytest.mark.parametrize("situation", [s for s in Situation if s is not Situation.NO_TRAINING])
def test_mostly_moderate_week_offers_to_swap_in_easy_days(situation: Situation) -> None:
    """中強度寄りの週は、中強度の一部を低強度に置き換える選択肢を出す。足す形にはしない。"""
    options = fallback_review(
        week(situation, rest_days_before=20), effort=effort(mostly_moderate=True)
    ).options

    swap = [o for o in options if o.label == "Swap in easy days"]
    assert len(swap) == 1
    assert adds_load(f"{swap[0].label} {swap[0].description}") == []


@pytest.mark.parametrize("situation", [Situation.FRESH, Situation.STEADY])
def test_swap_replaces_the_same_as_now_option(situation: Situation) -> None:
    """「今と同じ」選択肢は、今の配分を続けることになるので、置き換える選択肢と替える。"""
    labels = [
        o.label
        for o in fallback_review(week(situation), effort=effort(mostly_moderate=True)).options
    ]

    assert "Keep it steady" not in labels
    assert "Keep the rhythm" not in labels
    assert "Swap in easy days" in labels


def test_heavy_and_mostly_moderate_week_swaps_without_adding() -> None:
    """量が多めで中強度寄りの週も、増やす選択肢は出さずに置き換える選択肢を出す。"""
    review = fallback_review(
        week(Situation.STEADY), effort=effort(Volume.HEAVY, mostly_moderate=True)
    )
    text = " ".join([review.script, *(f"{o.label} {o.description}" for o in review.options)])

    assert adds_load(text) == []
    assert "Swap in easy days" in {o.label for o in review.options}


# 状況ごとの締め。いつもどおり・少なめの週も、この締めを残す
CLOSINGS = [
    pytest.param(Situation.FATIGUED, False, "A lighter week helps the work", id="fatigued"),
    pytest.param(Situation.FRESH, False, "add a little more", id="fresh"),
    pytest.param(Situation.FRESH, True, "listen to how your body feels", id="fresh_health_flag"),
    pytest.param(Situation.STEADY, False, "Keeping this rhythm", id="steady"),
]


@pytest.mark.parametrize(("situation", "health_flag", "closing"), CLOSINGS)
@pytest.mark.parametrize("volume", [Volume.USUAL, Volume.LIGHT])
def test_usual_and_light_weeks_keep_the_closing_of_the_situation(
    situation: Situation, health_flag: bool, closing: str, volume: Volume
) -> None:
    """いつもどおり・少なめは、状況の締め（回復を勧める、増やしてよい、体の声を聞く）を消すと
    助言とずれるので、締めを残して事実だけを足す。褒め言葉や「休んでよい」は言わない。"""
    script = fallback_review(week(situation), health_flag, effort(volume)).script

    assert closing in script
    assert script.index("Your load") < script.index(closing)
    for praise in ("consistency", "Rest counts", "perfectly fine"):
        assert praise not in script


def test_hard_spike_line_says_only_what_the_judgment_checked() -> None:
    """hard_spike は高強度の時間の増え方を比べただけで、負荷の増えた分の大半が高強度だったかは
    確かめていない。過去は毎週、低強度 120 分・高強度 0 分、今週は低強度 240 分・高強度 1 分でも
    立つ。セリフは「負荷が多く、高強度の時間も増えた」までにし、原因を断定しない。"""
    past = [PastWeek(load=100.0, high_sec=0)] * 9
    e = judge_effort(205.0, 0, ZoneTimes(low=240 * 60, mid=0, high=60), past)
    assert e.hard_spike is True

    script = fallback_review(week(Situation.STEADY), effort=e).script

    assert "hard-effort time went up too" in script
    for overstated in ("mostly", "mainly", "came from", "because of"):
        assert overstated not in script
