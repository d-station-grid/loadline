from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.fallback_review import fallback_review
from app.domain.situation import Situation
from app.models import User, WeeklyReview, WeeklyReviewOption, Workout
from app.services.dashboard import build_dashboard
from app.services.reviews import (
    HeartRateSettingsMissingError,
    create_review,
    judge_review_week,
    latest_review,
)
from tests.factories import (
    UserFactory,
    WeeklyReviewFactory,
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

    week = await judge_review_week(session, user, MONDAY)

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

    week = await judge_review_week(session, user, MONDAY)

    assert week.workouts == 1
    assert week.rest_days_before == 0
    assert week.workouts_change == 0


async def test_fitness_and_fatigue_match_the_dashboard(session: AsyncSession) -> None:
    """アバターが話す数字の元は、チャートと同じ計算。"""
    user = await _user()
    await _rides_every_other_day(user, date(2026, 8, 1), SUNDAY)

    week = await judge_review_week(session, user, MONDAY)
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
        await judge_review_week(session, user, MONDAY)


async def test_first_week_has_nothing_to_compare(session: AsyncSession) -> None:
    """その週より前に記録がなければ、前の週との差は出さない。"""
    user = await _user()
    await _ride(user, "2026-10-13T07:00")

    week = await judge_review_week(session, user, MONDAY)

    assert week.rest_days_before is None
    assert week.workouts_change is None
    assert week.situation == Situation.NOT_ENOUGH_DATA


async def test_create_review_saves_the_fallback_script_and_options(session: AsyncSession) -> None:
    user = await _user()
    await _rides_every_other_day(user, date(2026, 8, 1), SUNDAY)

    review, created = await create_review(session, user, today=TODAY)

    expected = fallback_review(await judge_review_week(session, user, MONDAY))
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


async def test_latest_review_is_the_newest_period_of_the_user(session: AsyncSession) -> None:
    me, other = await UserFactory.create_batch_async(2)
    older = await WeeklyReviewFactory.create_async(user_id=me.id, period_start=date(2026, 10, 5))
    newer = await WeeklyReviewFactory.create_async(user_id=me.id, period_start=date(2026, 10, 12))
    await WeeklyReviewFactory.create_async(user_id=other.id, period_start=date(2026, 10, 19))

    latest = await latest_review(session, me.id)

    assert latest is not None
    assert latest.id == newer.id != older.id
    assert await latest_review(session, other.id) is not None
    assert await latest_review(session, 0) is None
