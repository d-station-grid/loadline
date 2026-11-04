import json
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.domain.fallback_review import ReviewContent, ReviewOption, fallback_review
from app.domain.line_check import LineCheck
from app.domain.note_check import NoteCheck
from app.domain.review_prompt import NoteForReview
from app.domain.situation import Situation
from app.models import User, WeeklyReview, WeeklyReviewOption, Workout
from app.services.dashboard import build_dashboard
from app.services.reviews import (
    HeartRateSettingsMissingError,
    ReviewClosedError,
    ReviewNotFoundError,
    create_review,
    current_review,
    judge_review_week,
    notes_for_review,
    review_material,
    select_option,
)
from tests.factories import (
    NoteFactory,
    UserFactory,
    WeeklyReviewFactory,
    WeeklyReviewOptionFactory,
    WorkoutFactory,
    WorkoutHeartRateFactory,
)

JST = ZoneInfo("Asia/Tokyo")
# 2026-10-12（月）〜10-18（日）。振り返りの曜日が月曜なら、10-19〜10-25 の今日はこの週
MONDAY = date(2026, 10, 12)
SUNDAY = date(2026, 10, 18)
TODAY = date(2026, 10, 20)


async def _user(**fields: Any) -> User:
    defaults: dict[str, Any] = {
        "max_heart_rate": 177,
        "resting_heart_rate": 75,
        "timezone": "Asia/Tokyo",
        "review_weekday": 0,
    }
    return await UserFactory.create_async(**{**defaults, **fields})


async def _ride(user: User, start: str, minutes: int = 60, bpm: int | None = 140) -> Workout:
    """日本時間で start に始まるサイクリング。bpm が None なら心拍なし。"""
    started_at = datetime.fromisoformat(start).replace(tzinfo=JST)
    workout = await WorkoutFactory.create_async(
        user_id=user.id, started_at=started_at, duration_sec=minutes * 60
    )
    if bpm is not None:
        await WorkoutHeartRateFactory.create_batch_async(
            minutes,
            workout_id=workout.id,
            min_bpm=bpm - 5,
            avg_bpm=bpm,
            max_bpm=bpm + 5,
        )
    return workout


async def _rides_every_other_day(user: User, first: date, last: date) -> None:
    day = first
    while day <= last:
        await _ride(user, f"{day.isoformat()}T07:00")
        day += timedelta(days=2)


async def test_week_material_is_counted_in_the_users_timezone(session: AsyncSession) -> None:
    """回数・時間・休んだ日数・前の週との差を、利用者のタイムゾーンの日付で数える。"""
    user = await _user()
    await _ride(user, "2026-08-01T10:00")
    await _ride(user, "2026-10-08T07:00", minutes=60)  # 前の週
    await _ride(user, "2026-10-13T07:00", minutes=45)
    await _ride(user, "2026-10-15T07:00", minutes=30, bpm=None)
    await _ride(user, "2026-10-19T00:30")  # 次の週（UTC では 10-18 だが、日本時間では 10-19）

    week = await judge_review_week(session, user, MONDAY, TODAY)

    assert (week.start, week.end) == (MONDAY, SUNDAY)
    assert week.workouts == 2
    assert week.total_sec == 75 * 60
    assert week.unknown_load_days == 1
    assert week.rest_days_before == 4  # 10-09〜10-12
    assert week.workouts_change == 1
    assert week.total_sec_change == 15 * 60
    # 心拍のない日があるので、割合を使う判定はしない
    assert week.situation == Situation.NOT_ENOUGH_DATA


async def test_week_boundary_follows_the_users_midnight(session: AsyncSession) -> None:
    """日曜 23:30 は前の週、月曜 0:30 はその週。どちらも日本時間。"""
    user = await _user()
    await _ride(user, "2026-10-11T23:30")
    await _ride(user, "2026-10-12T00:30")

    week = await judge_review_week(session, user, MONDAY, TODAY)

    assert week.workouts == 1
    assert week.rest_days_before == 0
    assert week.workouts_change == 0


async def test_fitness_and_fatigue_match_the_dashboard(session: AsyncSession) -> None:
    """アバターが話す数字の元は、チャートと同じ計算。"""
    user = await _user()
    await _rides_every_other_day(user, date(2026, 8, 1), SUNDAY)

    week = await judge_review_week(session, user, MONDAY, TODAY)
    dashboard = await build_dashboard(session, user, since=SUNDAY, until=SUNDAY, sport="all")
    previous = await build_dashboard(
        session,
        user,
        since=MONDAY - timedelta(days=1),
        until=MONDAY - timedelta(days=1),
        sport="all",
    )

    assert week.fitness == pytest.approx(dashboard.days[0].fitness)
    assert week.fatigue == pytest.approx(dashboard.days[0].fatigue)
    assert week.fitness_change == pytest.approx(
        dashboard.days[0].fitness - previous.days[0].fitness
    )
    assert week.situation in (Situation.STEADY, Situation.FRESH, Situation.FATIGUED)


async def test_without_heart_rate_settings_the_week_cannot_be_judged(
    session: AsyncSession,
) -> None:
    user = await _user(max_heart_rate=None)

    with pytest.raises(HeartRateSettingsMissingError):
        await judge_review_week(session, user, MONDAY, TODAY)


async def test_first_week_has_nothing_to_compare(session: AsyncSession) -> None:
    """その週より前に記録がなければ、前の週との差は出さない。"""
    user = await _user()
    await _ride(user, "2026-10-13T07:00")

    week = await judge_review_week(session, user, MONDAY, TODAY)

    assert week.rest_days_before is None
    assert week.workouts_change is None
    assert week.situation == Situation.NOT_ENOUGH_DATA


async def test_create_review_saves_the_fallback_script_and_options(session: AsyncSession) -> None:
    user = await _user()
    await _rides_every_other_day(user, date(2026, 8, 1), SUNDAY)

    review, created = await create_review(session, user, today=TODAY)

    expected = fallback_review(await judge_review_week(session, user, MONDAY, TODAY))
    assert created
    assert (review.period_start, review.period_end) == (MONDAY, SUNDAY)
    assert review.script == expected.script
    assert review.is_fallback
    assert review.status == "completed"
    assert [(o.position, o.label, o.description) for o in review.options] == [
        (i, o.label, o.description) for i, o in enumerate(expected.options)
    ]
    assert all(o.selected_at is None for o in review.options)


async def test_create_review_twice_returns_the_same_review(session: AsyncSession) -> None:
    """同じ週の振り返りは作り直さない。記録が増えても、最初に作ったものを返す。"""
    user = await _user()
    first, _ = await create_review(session, user, today=TODAY)
    await _ride(user, "2026-10-14T07:00")

    second, created = await create_review(session, user, today=TODAY + timedelta(days=3))

    assert not created
    assert second == first
    assert await session.scalar(select(func.count()).select_from(WeeklyReview)) == 1
    assert await session.scalar(select(func.count()).select_from(WeeklyReviewOption)) == len(
        first.options
    )


async def test_create_review_without_any_workout(session: AsyncSession) -> None:
    """まだ記録がない人にも、記録が足りない週の定型で振り返りを作る。"""
    user = await _user()

    review, _ = await create_review(session, user, today=TODAY)

    assert review.situation == Situation.NOT_ENOUGH_DATA
    assert review.script.startswith("I'm still getting to know your training.")


async def test_review_weekday_and_timezone_decide_the_week(session: AsyncSession) -> None:
    """曜日が水曜なら、10-20（火）の今日は 10-14（水）の回で 10-07〜10-13。"""
    user = await _user(review_weekday=2)

    review, _ = await create_review(session, user, today=TODAY)

    assert (review.period_start, review.period_end) == (date(2026, 10, 7), date(2026, 10, 13))


async def test_a_week_that_has_not_ended_cannot_be_judged(session: AsyncSession) -> None:
    """週の最終日の値は、今日より前に終わった週にしかない。"""
    user = await _user()

    with pytest.raises(ValueError, match="before today"):
        await judge_review_week(session, user, MONDAY, today=SUNDAY)


async def test_review_can_be_created_for_a_today_after_the_machine_clock(
    session: AsyncSession,
) -> None:
    """渡した今日で週を決め、ダッシュボードの計算も同じ今日で切る。マシンの日付には頼らない。"""
    user = await _user()
    await _ride(user, "2030-01-02T07:00")

    review, created = await create_review(session, user, today=date(2030, 1, 8))

    assert created
    assert (review.period_start, review.period_end) == (date(2029, 12, 31), date(2030, 1, 6))


async def test_current_review_is_the_review_of_the_current_week(session: AsyncSession) -> None:
    """今の週で探す。いちばん新しい期間の行でも、今の週でなければ返さない。"""
    me = await _user()
    other = await _user()
    current = await WeeklyReviewFactory.create_async(user_id=me.id, period_start=MONDAY)
    # 振り返りの曜日を変える前に作った、今の週より後に始まる回
    await WeeklyReviewFactory.create_async(user_id=me.id, period_start=date(2026, 10, 14))

    found = await current_review(session, me, today=TODAY)

    assert found is not None
    assert found.id == current.id
    assert await current_review(session, other, today=TODAY) is None


async def _review_with_options(
    user: User, start: date, chosen: int | None = None
) -> tuple[int, list[int]]:
    """start に始まる振り返りと 3 つの選択肢の id。chosen を渡すと、その位置を選んだことにする。"""
    review = await WeeklyReviewFactory.create_async(user_id=user.id, period_start=start)
    option_ids = []
    for i, label in enumerate(["Rest fully", "Go easy", "Short and light"]):
        option = await WeeklyReviewOptionFactory.create_async(
            weekly_review_id=review.id,
            position=i,
            label=label,
            description=f"{label}.",
            selected_at=datetime(2026, 10, 1, tzinfo=JST) if i == chosen else None,
        )
        option_ids.append(option.id)
    return review.id, option_ids


def _selected(review_options: list[Any]) -> list[str]:
    return [o.label for o in review_options if o.selected_at is not None]


async def test_select_option_saves_the_choice(session: AsyncSession) -> None:
    user = await _user()
    review_id, option_ids = await _review_with_options(user, MONDAY)

    out = await select_option(session, user, review_id, option_ids[1], today=TODAY)

    assert _selected(out.options) == ["Go easy"]
    assert out.options[1].selected_at is not None


async def test_select_option_again_replaces_the_previous_choice(session: AsyncSession) -> None:
    user = await _user()
    review_id, option_ids = await _review_with_options(user, MONDAY)
    await select_option(session, user, review_id, option_ids[0], today=TODAY)

    out = await select_option(session, user, review_id, option_ids[2], today=TODAY)

    assert _selected(out.options) == ["Short and light"]
    saved = await session.scalars(
        select(WeeklyReviewOption.label).where(WeeklyReviewOption.selected_at.is_not(None))
    )
    assert list(saved) == ["Short and light"]


async def test_select_the_same_option_keeps_the_first_time(session: AsyncSession) -> None:
    user = await _user()
    review_id, option_ids = await _review_with_options(user, MONDAY)
    first = await select_option(session, user, review_id, option_ids[1], today=TODAY)

    again = await select_option(session, user, review_id, option_ids[1], today=TODAY)

    assert again.options[1].selected_at == first.options[1].selected_at


async def test_select_option_answers_its_own_choice_when_another_follows(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """コミットの直後に別のリクエストが選び直しても、応答の選択済みは自分の 1 つだけ。

    session fixture は 1 本の接続を巻き戻す作りで同時実行を再現できないので、
    ここだけ接続を 2 本張って本当に commit し、終わりに利用者ごと消す。
    """
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        user = UserFactory.build(
            max_heart_rate=177, resting_heart_rate=75, timezone="Asia/Tokyo", review_weekday=0
        )
        s.add(user)
        await s.flush()
        review = WeeklyReviewFactory.build(user_id=user.id, period_start=MONDAY)
        s.add(review)
        await s.flush()
        options = [
            WeeklyReviewOptionFactory.build(weekly_review_id=review.id, position=i)
            for i in range(2)
        ]
        s.add_all(options)
        await s.commit()
        user_id, review_id = user.id, review.id
        first, second = (o.id for o in options)

    try:
        async with factory() as a:
            real_commit = a.commit

            async def commit_then_another_selects() -> None:
                await real_commit()
                async with factory() as b:
                    other = await b.get(User, user_id)
                    assert other is not None
                    await select_option(b, other, review_id, second, today=TODAY)

            monkeypatch.setattr(a, "commit", commit_then_another_selects)
            me = await a.get(User, user_id)
            assert me is not None
            out = await select_option(a, me, review_id, first, today=TODAY)

        assert [o.id for o in out.options if o.selected_at is not None] == [first]
        async with factory() as s:
            saved = await s.scalars(
                select(WeeklyReviewOption.id).where(
                    WeeklyReviewOption.weekly_review_id == review_id,
                    WeeklyReviewOption.selected_at.is_not(None),
                )
            )
            assert list(saved) == [second]
    finally:
        async with factory() as s:
            await s.execute(delete(User).where(User.id == user_id))
            await s.commit()


async def test_select_option_of_a_past_week_is_closed(session: AsyncSession) -> None:
    """過ぎた週の選択は、次の週の材料に使った後なので変えない。"""
    user = await _user()
    past_id, option_ids = await _review_with_options(user, MONDAY - timedelta(weeks=1), chosen=0)

    with pytest.raises(ReviewClosedError):
        await select_option(session, user, past_id, option_ids[1], today=TODAY)


async def test_select_option_of_someone_else_is_not_found(session: AsyncSession) -> None:
    me = await _user()
    other = await _user()
    their_review, their_options = await _review_with_options(other, MONDAY)
    my_review, _ = await _review_with_options(me, MONDAY)

    # 他人の振り返り
    with pytest.raises(ReviewNotFoundError):
        await select_option(session, me, their_review, their_options[0], today=TODAY)
    # 自分の振り返りに、他人の振り返りの選択肢
    with pytest.raises(ReviewNotFoundError):
        await select_option(session, me, my_review, their_options[0], today=TODAY)


async def test_material_has_the_choice_of_the_week_before(session: AsyncSession) -> None:
    user = await _user()
    await _review_with_options(user, MONDAY - timedelta(weeks=1), chosen=1)

    material = await review_material(session, user, MONDAY, TODAY)

    assert material.previous_choice == ReviewOption("Go easy", "Go easy.")
    assert material.week == await judge_review_week(session, user, MONDAY, TODAY)


@pytest.mark.parametrize(
    ("weeks_before", "chosen"),
    [
        (1, None),  # 前の週に選んでいない
        (2, 1),  # 選んだのは 2 週前。間が空いた回の選択は渡さない
    ],
)
async def test_material_without_a_choice_of_the_week_before(
    session: AsyncSession, weeks_before: int, chosen: int | None
) -> None:
    user = await _user()
    await _review_with_options(user, MONDAY - timedelta(weeks=weeks_before), chosen=chosen)

    material = await review_material(session, user, MONDAY, TODAY)

    assert material.previous_choice is None


async def test_material_does_not_read_someone_elses_choice(session: AsyncSession) -> None:
    me = await _user()
    other = await _user()
    await _review_with_options(other, MONDAY - timedelta(weeks=1), chosen=0)

    material = await review_material(session, me, MONDAY, TODAY)

    assert material.previous_choice is None


async def test_create_review_does_not_change_the_script_by_the_previous_choice(
    session: AsyncSession,
) -> None:
    """定型のセリフは前の週の選択を読まない。"""
    user = await _user()
    await _review_with_options(user, MONDAY - timedelta(weeks=1), chosen=2)

    review, _ = await create_review(session, user, today=TODAY)

    assert (
        review.script
        == fallback_review(await judge_review_week(session, user, MONDAY, TODAY)).script
    )


WRITTEN = ReviewContent(
    script="A calm week of riding. " + " ".join(["word"] * 30),
    options=(
        ReviewOption("Rest fully", "Take a few days off."),
        ReviewOption("Keep it steady", "Train the same way as last week."),
    ),
)


class FakeWriter:
    """受け取った本文を控え、決めた結果を返す。"""

    def __init__(self, result: ReviewContent | None) -> None:
        self.result = result
        self.prompts: list[str] = []

    async def write(self, contents: str) -> ReviewContent | None:
        self.prompts.append(contents)
        return self.result

    def data(self) -> Any:
        """最後に受け取った本文の JSON の部分。"""
        text = self.prompts[-1]
        return json.loads(text[text.index("{") :])


SAFE = LineCheck(pushes_harder=0.02, medical_advice=0.01)
NO_HEALTH_NOTE = NoteCheck(mentions_health=0.03)


class FakeChecker:
    """受け取ったセリフとメモを控え、決めた結果を返す。"""

    def __init__(
        self, result: LineCheck | None, notes_result: NoteCheck | None = NO_HEALTH_NOTE
    ) -> None:
        self.result = result
        self.notes_result = notes_result
        self.contents: list[ReviewContent] = []
        self.notes: list[list[NoteForReview]] = []

    async def check(self, content: ReviewContent) -> LineCheck | None:
        self.contents.append(content)
        return self.result

    async def check_notes(self, notes: Sequence[NoteForReview]) -> NoteCheck | None:
        self.notes.append(list(notes))
        return self.notes_result


async def test_create_review_saves_what_the_writer_wrote(session: AsyncSession) -> None:
    """Jev で話してよいと確かめられたら、Gemini の文を保存する。"""
    user = await _user()
    await _rides_every_other_day(user, date(2026, 8, 1), SUNDAY)
    writer = FakeWriter(WRITTEN)
    checker = FakeChecker(SAFE)

    review, created = await create_review(session, user, writer, checker, today=TODAY)

    assert created
    assert checker.contents == [WRITTEN]
    assert review.script == WRITTEN.script
    assert not review.is_fallback
    assert [(o.position, o.label, o.description) for o in review.options] == [
        (0, "Rest fully", "Take a few days off."),
        (1, "Keep it steady", "Train the same way as last week."),
    ]
    # 判定はコードで決めたものを渡し、保存する
    assert writer.data()["situation"] == review.situation.value


async def test_create_review_falls_back_when_the_writer_cannot_write(
    session: AsyncSession,
) -> None:
    """Gemini が書けなければ（失敗、時間切れ）、確かめずに定型で作る。"""
    user = await _user()
    await _rides_every_other_day(user, date(2026, 8, 1), SUNDAY)
    writer = FakeWriter(None)
    checker = FakeChecker(SAFE)

    review, created = await create_review(session, user, writer, checker, today=TODAY)

    expected = fallback_review(await judge_review_week(session, user, MONDAY, TODAY))
    assert created
    assert len(writer.prompts) == 1
    assert checker.contents == []
    assert review.is_fallback
    assert review.script == expected.script


async def test_existing_review_does_not_call_the_writer_again(session: AsyncSession) -> None:
    """作った週は作り直さないので、LLM も呼ばない。"""
    user = await _user()
    first, _ = await create_review(
        session, user, FakeWriter(WRITTEN), FakeChecker(SAFE), today=TODAY
    )
    writer = FakeWriter(None)
    checker = FakeChecker(SAFE)

    second, created = await create_review(session, user, writer, checker, today=TODAY)

    assert not created
    assert second == first
    assert writer.prompts == []
    assert checker.contents == []


async def test_writer_gets_the_notes_of_the_week_and_the_previous_choice(
    session: AsyncSession,
) -> None:
    user = await _user()
    other = await _user()
    await NoteFactory.create_async(user_id=user.id, date=MONDAY - timedelta(days=1), body="Before")
    await NoteFactory.create_async(user_id=user.id, date=SUNDAY, label="Hills", body="Long ride")
    await NoteFactory.create_async(user_id=user.id, date=MONDAY, body="Slept badly")
    await NoteFactory.create_async(user_id=user.id, date=SUNDAY + timedelta(days=1), body="After")
    await NoteFactory.create_async(user_id=other.id, date=MONDAY + timedelta(days=2), body="Other")
    await _review_with_options(user, MONDAY - timedelta(weeks=1), chosen=1)
    writer = FakeWriter(WRITTEN)

    await create_review(session, user, writer, FakeChecker(SAFE), today=TODAY)

    data = writer.data()
    # その週の 7 日の、本人のメモだけを日付順に
    assert data["notes"] == [
        {"date": "2026-10-12", "label": None, "text": "Slept badly"},
        {"date": "2026-10-18", "label": "Hills", "text": "Long ride"},
    ]
    assert data["last_choice"] == {"label": "Go easy", "description": "Go easy."}


async def test_notes_are_not_sent_when_the_user_turned_it_off(session: AsyncSession) -> None:
    """「メモを AI に送らない」設定なら、メモを渡さない。振り返りは Gemini で作る。"""
    user = await _user(send_notes_to_ai=False)
    await NoteFactory.create_async(user_id=user.id, date=MONDAY, body="Back pain again")
    writer = FakeWriter(WRITTEN)

    review, _ = await create_review(session, user, writer, FakeChecker(SAFE), today=TODAY)

    assert writer.data()["notes"] == []
    assert "Back pain" not in writer.prompts[-1]
    assert not review.is_fallback
    assert await notes_for_review(session, user, MONDAY, SUNDAY) == []


@pytest.mark.parametrize(
    "check",
    [
        pytest.param(LineCheck(pushes_harder=0.8, medical_advice=0.0), id="pushes_harder"),
        pytest.param(LineCheck(pushes_harder=0.0, medical_advice=0.35), id="medical_advice"),
    ],
)
async def test_create_review_falls_back_when_the_line_is_flagged(
    session: AsyncSession, check: LineCheck, caplog: pytest.LogCaptureFixture
) -> None:
    """Jev で引っかかったら、Gemini の文は話さずに定型で作る。"""
    user = await _user()
    await _rides_every_other_day(user, date(2026, 8, 1), SUNDAY)
    checker = FakeChecker(check)

    review, created = await create_review(session, user, FakeWriter(WRITTEN), checker, today=TODAY)

    expected = fallback_review(await judge_review_week(session, user, MONDAY, TODAY))
    assert created
    assert checker.contents == [WRITTEN]
    assert review.is_fallback
    assert review.script == expected.script
    assert [o.label for o in review.options] == [o.label for o in expected.options]
    flagged_logs = [r for r in caplog.records if "flagged" in r.message]
    assert [r.levelname for r in flagged_logs] == ["WARNING"]
    # 名前と確率を残し、セリフは残さない
    name, yes = ("pushes_harder", "0.80") if check.pushes_harder else ("medical_advice", "0.35")
    assert f"{name}={yes}" in flagged_logs[0].getMessage()
    assert WRITTEN.script not in flagged_logs[0].getMessage()


async def test_create_review_falls_back_when_the_line_cannot_be_checked(
    session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    """Jev で確かめられなければ（失敗、時間切れ、想定外の応答）、定型で作る。"""
    user = await _user()
    await _rides_every_other_day(user, date(2026, 8, 1), SUNDAY)
    checker = FakeChecker(None)

    review, _ = await create_review(session, user, FakeWriter(WRITTEN), checker, today=TODAY)

    expected = fallback_review(await judge_review_week(session, user, MONDAY, TODAY))
    assert checker.contents == [WRITTEN]
    assert review.is_fallback
    assert review.script == expected.script
    assert any("could not check" in r.message for r in caplog.records)


async def test_create_review_without_a_checker_does_not_speak_what_gemini_writes(
    session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    """Jev がなければ（キーが空）、確かめていない文は話さない。Gemini も呼ばずに定型で作る。"""
    user = await _user()
    await _rides_every_other_day(user, date(2026, 8, 1), SUNDAY)
    await NoteFactory.create_async(user_id=user.id, date=MONDAY, body="Back pain again")
    writer = FakeWriter(WRITTEN)

    review, created = await create_review(session, user, writer, None, today=TODAY)

    expected = fallback_review(await judge_review_week(session, user, MONDAY, TODAY))
    assert created
    assert writer.prompts == []
    assert review.is_fallback
    assert review.script == expected.script
    assert any("no line checker" in r.message for r in caplog.records)


def _adds_load(labels: list[str]) -> list[str]:
    return [label for label in labels if label in {"Add a bit more", "Add one session"}]


async def test_notes_are_checked_with_jev_before_the_writer(session: AsyncSession) -> None:
    """その週のメモを Jev で確かめてから書かせる。痛みに触れていなければ、順調な週は増やす
    選択肢を出してよい。"""
    user = await _user()
    await _rides_every_other_day(user, date(2026, 8, 1), SUNDAY)
    await NoteFactory.create_async(user_id=user.id, date=MONDAY, label="Work", body="Busy week")
    writer = FakeWriter(WRITTEN)
    checker = FakeChecker(SAFE, NoteCheck(mentions_health=0.34))

    await create_review(session, user, writer, checker, today=TODAY)

    assert checker.notes == [[NoteForReview(day=MONDAY, label="Work", body="Busy week")]]
    assert writer.data()["situation"] == "steady"
    assert writer.data()["may_offer_more"] is True


async def test_health_flag_keeps_the_writer_from_offering_more(session: AsyncSession) -> None:
    """痛みや病気に触れたメモがある週は、順調な週でも増やす選択肢を出させない。コードで決める。"""
    user = await _user()
    await _rides_every_other_day(user, date(2026, 8, 1), SUNDAY)
    await NoteFactory.create_async(user_id=user.id, date=MONDAY, body="Knee hurts on stairs")
    writer = FakeWriter(WRITTEN)
    checker = FakeChecker(SAFE, NoteCheck(mentions_health=0.35))

    review, _ = await create_review(session, user, writer, checker, today=TODAY)

    assert writer.data()["situation"] == "steady"
    assert writer.data()["may_offer_more"] is False
    assert not review.is_fallback


async def test_health_flag_also_removes_more_from_the_fixed_options(session: AsyncSession) -> None:
    """フラグが立った週に Gemini の文が引っかかって定型になっても、増やす選択肢は出さない。"""
    user = await _user()
    await _rides_every_other_day(user, date(2026, 8, 1), SUNDAY)
    await NoteFactory.create_async(user_id=user.id, date=MONDAY, body="Caught a cold")
    flagged_line = LineCheck(pushes_harder=0.9, medical_advice=0.0)
    checker = FakeChecker(flagged_line, NoteCheck(mentions_health=0.8))

    review, _ = await create_review(session, user, FakeWriter(WRITTEN), checker, today=TODAY)

    week = await judge_review_week(session, user, MONDAY, TODAY)
    labels = [o.label for o in review.options]
    assert review.is_fallback
    assert _adds_load([o.label for o in fallback_review(week).options]) != []
    assert _adds_load(labels) == []
    assert labels == [o.label for o in fallback_review(week, health_flag=True).options]


async def test_notes_that_cannot_be_checked_fall_back_without_more(
    session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    """メモを Jev で確かめられなければ、Gemini は呼ばずに定型にする。増やす選択肢も外す
    （痛みに触れていないと確かめられていないので、安全側に倒す）。"""
    user = await _user()
    await _rides_every_other_day(user, date(2026, 8, 1), SUNDAY)
    await NoteFactory.create_async(user_id=user.id, date=MONDAY, body="Back pain again")
    writer = FakeWriter(WRITTEN)
    checker = FakeChecker(SAFE, None)

    review, created = await create_review(session, user, writer, checker, today=TODAY)

    assert created
    assert writer.prompts == []
    assert checker.contents == []
    assert review.is_fallback
    assert _adds_load([o.label for o in review.options]) == []
    logs = [r.getMessage() for r in caplog.records if "could not check the notes" in r.message]
    assert len(logs) == 1
    assert "Back pain" not in logs[0]


async def test_health_flag_log_does_not_keep_the_notes(
    session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    """フラグが立ったことと確率はログに残し、メモの文は残さない。"""
    caplog.set_level("INFO")
    user = await _user()
    await _rides_every_other_day(user, date(2026, 8, 1), SUNDAY)
    await NoteFactory.create_async(user_id=user.id, date=MONDAY, body="Knee hurts on stairs")

    await create_review(
        session,
        user,
        FakeWriter(WRITTEN),
        FakeChecker(SAFE, NoteCheck(mentions_health=0.72)),
        today=TODAY,
    )

    logs = [r.getMessage() for r in caplog.records if "pain or sickness" in r.message]
    assert len(logs) == 1
    assert "mentions_health=0.72" in logs[0]
    assert "Knee" not in logs[0]


@pytest.mark.parametrize(
    "send_notes_to_ai", [pytest.param(True, id="no_notes"), pytest.param(False, id="turned_off")]
)
async def test_notes_are_not_checked_when_there_are_none_to_send(
    session: AsyncSession, send_notes_to_ai: bool
) -> None:
    """メモがない週と、「メモを AI に送らない」設定では、Jev にもメモを送らない。
    フラグは立てない。"""
    user = await _user(send_notes_to_ai=send_notes_to_ai)
    await _rides_every_other_day(user, date(2026, 8, 1), SUNDAY)
    if not send_notes_to_ai:
        await NoteFactory.create_async(user_id=user.id, date=MONDAY, body="Back pain again")
    writer = FakeWriter(WRITTEN)
    checker = FakeChecker(SAFE)

    review, _ = await create_review(session, user, writer, checker, today=TODAY)

    assert checker.notes == []
    assert writer.data()["may_offer_more"] is True
    assert not review.is_fallback


async def test_notes_are_checked_even_without_the_writer(session: AsyncSession) -> None:
    """Gemini を切っていても、Jev があればメモを確かめ、定型から増やす選択肢を外す。"""
    user = await _user()
    await _rides_every_other_day(user, date(2026, 8, 1), SUNDAY)
    await NoteFactory.create_async(user_id=user.id, date=MONDAY, body="Knee hurts on stairs")
    checker = FakeChecker(SAFE, NoteCheck(mentions_health=0.8))

    review, created = await create_review(session, user, None, checker, today=TODAY)

    week = await judge_review_week(session, user, MONDAY, TODAY)
    assert created
    assert review.is_fallback
    assert len(checker.notes) == 1
    assert checker.contents == []
    assert _adds_load([o.label for o in review.options]) == []
    assert review.script == fallback_review(week, health_flag=True).script


@pytest.mark.parametrize(
    ("notes_result", "adds_load"),
    [
        pytest.param(NO_HEALTH_NOTE, True, id="no_pain"),
        pytest.param(None, False, id="cannot_check"),
    ],
)
async def test_without_the_writer_the_fixed_options_follow_the_note_check(
    session: AsyncSession, notes_result: NoteCheck | None, adds_load: bool
) -> None:
    """Gemini がないとき、痛みに触れていなければ今までどおり。確かめられなければ安全側。"""
    user = await _user()
    await _rides_every_other_day(user, date(2026, 8, 1), SUNDAY)
    await NoteFactory.create_async(user_id=user.id, date=MONDAY, body="Busy week")

    review, _ = await create_review(
        session, user, None, FakeChecker(SAFE, notes_result), today=TODAY
    )

    assert review.is_fallback
    assert (_adds_load([o.label for o in review.options]) != []) is adds_load
