from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User, WeeklyReview, WeeklyReviewOption
from tests.factories import UserFactory, WeeklyReviewFactory, WeeklyReviewOptionFactory


async def test_same_period_is_not_saved_twice(session: AsyncSession) -> None:
    """同じ利用者の同じ期間の振り返りは 1 件だけ。二重に作ろうとしたら DB が止める。"""
    user = await UserFactory.create_async()
    first = await WeeklyReviewFactory.create_async(user_id=user.id)

    with pytest.raises(IntegrityError):
        await WeeklyReviewFactory.create_async(user_id=user.id, period_start=first.period_start)


async def test_same_period_for_another_user_is_fine(session: AsyncSession) -> None:
    me, other = await UserFactory.create_batch_async(2)
    mine = await WeeklyReviewFactory.create_async(user_id=me.id)

    theirs = await WeeklyReviewFactory.create_async(
        user_id=other.id, period_start=mine.period_start
    )

    assert theirs.id != mine.id


async def test_same_position_in_one_review_is_not_saved_twice(session: AsyncSession) -> None:
    user = await UserFactory.create_async()
    review = await WeeklyReviewFactory.create_async(user_id=user.id)
    await WeeklyReviewOptionFactory.create_async(weekly_review_id=review.id, position=0)

    with pytest.raises(IntegrityError):
        await WeeklyReviewOptionFactory.create_async(weekly_review_id=review.id, position=0)


async def test_only_one_option_per_review_can_be_selected(session: AsyncSession) -> None:
    """1 つの振り返りで選べるのは 1 つ。2 つ目を選ぼうとしたら DB が止める。"""
    user = await UserFactory.create_async()
    review = await WeeklyReviewFactory.create_async(user_id=user.id)
    chosen_at = datetime(2026, 9, 21, 8, 0, tzinfo=UTC)
    await WeeklyReviewOptionFactory.create_async(weekly_review_id=review.id, selected_at=chosen_at)

    with pytest.raises(IntegrityError):
        await WeeklyReviewOptionFactory.create_async(
            weekly_review_id=review.id, selected_at=chosen_at
        )


async def test_options_of_different_reviews_can_each_be_selected(session: AsyncSession) -> None:
    """選んでいない選択肢はいくつあってもよく、別の週ならそれぞれ 1 つずつ選べる。"""
    user = await UserFactory.create_async()
    first, second = await WeeklyReviewFactory.create_batch_async(2, user_id=user.id)
    chosen_at = datetime(2026, 9, 21, 8, 0, tzinfo=UTC)

    await WeeklyReviewOptionFactory.create_batch_async(2, weekly_review_id=first.id)
    await WeeklyReviewOptionFactory.create_async(weekly_review_id=first.id, selected_at=chosen_at)
    await WeeklyReviewOptionFactory.create_async(weekly_review_id=second.id, selected_at=chosen_at)

    count = await session.scalar(
        select(func.count())
        .select_from(WeeklyReviewOption)
        .where(WeeklyReviewOption.selected_at.is_not(None))
    )
    assert count == 2


async def test_deleting_a_user_deletes_reviews_and_options(session: AsyncSession) -> None:
    """アカウントの削除で、振り返りと選択肢も残らない。"""
    user = await UserFactory.create_async()
    review = await WeeklyReviewFactory.create_async(user_id=user.id)
    await WeeklyReviewOptionFactory.create_batch_async(3, weekly_review_id=review.id)
    await session.commit()

    await session.execute(delete(User).where(User.id == user.id))
    await session.commit()

    assert await session.scalar(select(func.count()).select_from(WeeklyReview)) == 0
    assert await session.scalar(select(func.count()).select_from(WeeklyReviewOption)) == 0
