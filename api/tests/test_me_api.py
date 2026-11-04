from collections.abc import Iterator

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Identity, InvalidTokenError, get_token_verifier
from app.core.internal_auth import get_internal_caller_verifier
from app.main import app
from app.models import (
    Base,
    IngestToken,
    Note,
    User,
    Vo2maxReading,
    WeeklyReview,
    WeeklyReviewOption,
    Workout,
    WorkoutHeartRate,
)
from app.routers.deps import get_account_deleter
from app.services.accounts import AccountDeleteError, delete_account
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
from tests.test_internal_api import FakeCallerVerifier

HEADERS = {"Authorization": "Bearer good"}


class FakeVerifier:
    def verify(self, token: str) -> Identity:
        if token == "good":
            return Identity(uid="uid-1", email="one@example.com")
        raise InvalidTokenError


class FakeDeleter:
    """消すよう頼まれた uid を控える。fail なら消せなかったことにする。"""

    def __init__(self, fail: bool = False) -> None:
        self.deleted: list[str] = []
        self.fail = fail

    async def delete(self, uid: str) -> None:
        if self.fail:
            raise AccountDeleteError
        self.deleted.append(uid)


@pytest.fixture
def deleter() -> Iterator[FakeDeleter]:
    fake = FakeDeleter()
    app.dependency_overrides[get_token_verifier] = FakeVerifier
    app.dependency_overrides[get_account_deleter] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_token_verifier, None)
    app.dependency_overrides.pop(get_account_deleter, None)


async def _user_with_everything(firebase_uid: str | None) -> User:
    """どの表にも 1 行以上ある利用者。"""
    user = await UserFactory.create_async(firebase_uid=firebase_uid)
    await IngestTokenFactory.create_async(user_id=user.id)
    workout = await WorkoutFactory.create_async(user_id=user.id)
    await WorkoutHeartRateFactory.create_batch_async(2, workout_id=workout.id)
    await Vo2maxReadingFactory.create_async(user_id=user.id)
    await NoteFactory.create_async(user_id=user.id)
    review = await WeeklyReviewFactory.create_async(user_id=user.id)
    await WeeklyReviewOptionFactory.create_batch_async(2, weekly_review_id=review.id)
    return user


async def _rows_of(session: AsyncSession, user_id: int) -> dict[str, int]:
    """表ごとの、その利用者の行の数。子の表は親をたどって数える。"""
    counts = {
        User.__tablename__: select(func.count()).where(User.id == user_id),
        IngestToken.__tablename__: select(func.count()).where(IngestToken.user_id == user_id),
        Workout.__tablename__: select(func.count()).where(Workout.user_id == user_id),
        WorkoutHeartRate.__tablename__: select(func.count())
        .select_from(WorkoutHeartRate)
        .join(Workout, WorkoutHeartRate.workout_id == Workout.id)
        .where(Workout.user_id == user_id),
        Vo2maxReading.__tablename__: select(func.count()).where(Vo2maxReading.user_id == user_id),
        Note.__tablename__: select(func.count()).where(Note.user_id == user_id),
        WeeklyReview.__tablename__: select(func.count()).where(WeeklyReview.user_id == user_id),
        WeeklyReviewOption.__tablename__: select(func.count())
        .select_from(WeeklyReviewOption)
        .join(WeeklyReview, WeeklyReviewOption.weekly_review_id == WeeklyReview.id)
        .where(WeeklyReview.user_id == user_id),
    }
    # 表を足したらここでも数える。数え漏れを残さない
    assert counts.keys() == Base.metadata.tables.keys()
    return {name: (await session.scalar(q)) or 0 for name, q in counts.items()}


async def test_delete_removes_every_row_of_the_user(
    client: AsyncClient, session: AsyncSession, deleter: FakeDeleter
) -> None:
    me = await _user_with_everything("uid-1")
    other = await _user_with_everything("someone-else")
    await session.commit()
    me_id, other_id = me.id, other.id
    others_before = await _rows_of(session, other_id)

    res = await client.delete("/me", headers=HEADERS)

    assert res.status_code == 204
    assert res.content == b""
    assert deleter.deleted == ["uid-1"]
    assert all(n == 0 for n in (await _rows_of(session, me_id)).values())
    # 別の利用者の行は 1 つも減らない
    assert all(n > 0 for n in others_before.values())
    assert await _rows_of(session, other_id) == others_before


async def test_firebase_failure_keeps_every_row(
    client: AsyncClient, session: AsyncSession, deleter: FakeDeleter
) -> None:
    me = await _user_with_everything("uid-1")
    await session.commit()
    me_id = me.id
    before = await _rows_of(session, me_id)
    deleter.fail = True

    res = await client.delete("/me", headers=HEADERS)

    # 何も消えていないので、もう一度呼べばやり直せる
    assert res.status_code == 502
    assert all(n > 0 for n in before.values())
    assert await _rows_of(session, me_id) == before


async def test_user_without_firebase_uid_is_deleted_without_firebase(
    session: AsyncSession, deleter: FakeDeleter
) -> None:
    # firebase_uid が NULL の人は窓口からは来ないので、service を直に呼ぶ
    user = await _user_with_everything(None)
    await session.commit()
    user_id = user.id

    await delete_account(session, user, deleter)

    assert deleter.deleted == []
    assert all(n == 0 for n in (await _rows_of(session, user_id)).values())


async def test_guest_cannot_delete(
    client: AsyncClient, session: AsyncSession, deleter: FakeDeleter
) -> None:
    # デモデータはゲストみんなで見るので消させない
    user = await UserFactory.create_async(firebase_uid="uid-1", is_demo=True)
    await session.commit()

    res = await client.delete("/me", headers=HEADERS)

    assert res.status_code == 403
    assert deleter.deleted == []
    assert (await _rows_of(session, user.id))[User.__tablename__] == 1


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer bad"}], ids=["none", "bad"])
async def test_delete_needs_login(
    client: AsyncClient, deleter: FakeDeleter, headers: dict[str, str]
) -> None:
    res = await client.delete("/me", headers=headers)

    assert res.status_code == 401
    assert deleter.deleted == []


async def test_task_for_the_deleted_user_is_skipped(
    client: AsyncClient, session: AsyncSession, deleter: FakeDeleter
) -> None:
    # 消す前に積まれた振り返りのタスクが、消した後に届く
    me = await _user_with_everything("uid-1")
    me.max_heart_rate, me.resting_heart_rate = 177, 75
    await session.commit()
    me_id = me.id
    await client.delete("/me", headers=HEADERS)
    app.dependency_overrides[get_internal_caller_verifier] = FakeCallerVerifier
    try:
        res = await client.post(
            f"/internal/reviews/users/{me_id}/weeks/2026-10-26",
            headers={"Authorization": "Bearer from-google"},
        )
    finally:
        app.dependency_overrides.pop(get_internal_caller_verifier, None)

    assert res.status_code == 200
    assert res.json() == {"result": "skipped", "review_id": None}
