from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import (
    IngestTokenFactory,
    NoteFactory,
    UserFactory,
    Vo2maxReadingFactory,
    WeeklyReviewFactory,
    WeeklyReviewOptionFactory,
    WorkoutFactory,
    WorkoutHeartRateFactory,
)


async def test_each_factory_saves_a_row(session: AsyncSession) -> None:
    """表の制約（NOT NULL、外部キー、一意）を満たす行が既定の値で作れる。"""
    user = await UserFactory.create_async()
    token = await IngestTokenFactory.create_async(user_id=user.id)
    workout = await WorkoutFactory.create_async(user_id=user.id)
    heart_rate = await WorkoutHeartRateFactory.create_async(workout_id=workout.id)
    vo2max = await Vo2maxReadingFactory.create_async(user_id=user.id)
    note = await NoteFactory.create_async(user_id=user.id)
    review = await WeeklyReviewFactory.create_async(user_id=user.id)
    option = await WeeklyReviewOptionFactory.create_async(weekly_review_id=review.id)

    assert user.timezone == "Asia/Tokyo"
    assert user.max_heart_rate is None
    assert token.revoked_at is None
    assert workout.ended_at - workout.started_at == timedelta(seconds=workout.duration_sec)
    assert heart_rate.workout_id == workout.id
    assert vo2max.user_id == user.id
    assert note.label is None
    assert review.period_end - review.period_start == timedelta(days=6)
    assert review.audio_path is None
    assert option.selected_at is None


async def test_many_rows_for_one_user_do_not_collide(session: AsyncSession) -> None:
    """既定の値のまま同じ利用者に何件作っても、一意制約で落ちない。"""
    first, second = await UserFactory.create_batch_async(2)
    await WorkoutFactory.create_batch_async(2, user_id=first.id)
    readings = await Vo2maxReadingFactory.create_batch_async(2, user_id=first.id)
    notes = await NoteFactory.create_batch_async(2, user_id=first.id)
    workout = await WorkoutFactory.create_async(user_id=first.id)
    heart_rates = await WorkoutHeartRateFactory.create_batch_async(2, workout_id=workout.id)
    reviews = await WeeklyReviewFactory.create_batch_async(2, user_id=first.id)
    options = await WeeklyReviewOptionFactory.create_batch_async(2, weekly_review_id=reviews[0].id)

    assert first.firebase_uid != second.firebase_uid
    assert readings[0].measured_at != readings[1].measured_at
    assert notes[0].date != notes[1].date
    assert heart_rates[1].recorded_at - heart_rates[0].recorded_at == timedelta(minutes=1)
    assert reviews[1].period_start - reviews[0].period_start == timedelta(weeks=1)
    assert options[0].position != options[1].position


async def test_default_uid_is_not_the_logged_in_one(session: AsyncSession) -> None:
    """テストの偽のログインは uid-1 を使う。既定で作った利用者が本人に化けない。"""
    users = await UserFactory.create_batch_async(3)

    assert all(u.firebase_uid and u.firebase_uid.startswith("factory-uid-") for u in users)
