from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import (
    IngestTokenFactory,
    UserFactory,
    Vo2maxReadingFactory,
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

    assert user.timezone == "Asia/Tokyo"
    assert user.max_heart_rate is None
    assert token.revoked_at is None
    assert workout.ended_at - workout.started_at == timedelta(seconds=workout.duration_sec)
    assert heart_rate.workout_id == workout.id
    assert vo2max.user_id == user.id


async def test_users_and_workouts_do_not_collide(session: AsyncSession) -> None:
    first, second = await UserFactory.create_batch_async(2)
    await WorkoutFactory.create_batch_async(2, user_id=first.id)

    assert first.firebase_uid != second.firebase_uid
