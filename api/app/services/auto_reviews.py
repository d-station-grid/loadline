"""振り返りを自動で作る相手を探す、1 人分を作る。

Scheduler が 1 時間おきに due_user_ids を呼び、見つかった人を 1 人ずつ Tasks に積む。
Tasks からは create_for_user が 1 人ずつ呼ばれる。
"""

import enum
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.auto_review import is_auto_review_time
from app.domain.calendar import today_for
from app.domain.review_week import review_period
from app.models import User, WeeklyReview
from app.services.reviews import HeartRateSettingsMissingError, ReviewWriter, create_review


async def due_user_ids(session: AsyncSession, now: datetime) -> list[int]:
    """now の時点で、振り返りを自動で作る相手の id（昇順）。

    ゲストではなく、心拍の設定があり、振り返りの曜日の 6 時を過ぎていて、今の週の
    振り返りがまだない人。時刻の判定は利用者ごとのタイムゾーンでするので、候補は
    Python の側で絞る。
    """
    candidates = (
        await session.execute(
            select(User.id, User.timezone, User.review_weekday)
            .where(
                User.is_demo.is_(False),
                User.max_heart_rate.is_not(None),
                User.resting_heart_rate.is_not(None),
            )
            .order_by(User.id)
        )
    ).all()
    # 振り返りの曜日の当日なので、今の週の初日は「今日の 7 日前」
    weeks = {
        c.id: review_period(today_for(c.timezone, now), c.review_weekday)[0]
        for c in candidates
        if is_auto_review_time(now, c.timezone, c.review_weekday)
    }
    if not weeks:
        return []
    rows = await session.execute(
        select(WeeklyReview.user_id, WeeklyReview.period_start).where(
            tuple_(WeeklyReview.user_id, WeeklyReview.period_start).in_(list(weeks.items()))
        )
    )
    made = {(user_id, start) for user_id, start in rows}
    return [user_id for user_id, start in weeks.items() if (user_id, start) not in made]


class AutoReviewResult(enum.StrEnum):
    CREATED = "created"
    # その週の振り返りはもうある（本人がボタンで作った、Tasks が同じ人を 2 回呼んだ）
    EXISTS = "exists"
    # 作れない相手。Tasks に再試行させても変わらないので、失敗にはしない
    SKIPPED = "skipped"


@dataclass(frozen=True)
class AutoReview:
    result: AutoReviewResult
    review_id: int | None = None


class UserNotFoundError(Exception):
    """その id の利用者がいない。"""


async def create_for_user(
    session: AsyncSession, user_id: int, writer: ReviewWriter | None
) -> AutoReview:
    """1 人分の今の週の振り返りを作る。作り方は本人がボタンで作るときと同じ。

    積んでから呼ばれるまでの間に、ゲストになった・心拍の設定を消した人は飛ばす。
    時刻は確かめ直さない。遅れて日をまたいでも、今の週は変わらないため。
    """
    user = await session.get(User, user_id)
    if user is None:
        raise UserNotFoundError
    if user.is_demo:
        return AutoReview(AutoReviewResult.SKIPPED)
    try:
        review, created = await create_review(session, user, writer)
    except HeartRateSettingsMissingError:
        return AutoReview(AutoReviewResult.SKIPPED)
    return AutoReview(AutoReviewResult.CREATED if created else AutoReviewResult.EXISTS, review.id)
