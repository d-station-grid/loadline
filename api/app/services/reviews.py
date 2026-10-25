"""週に 1 回の振り返りを作る、読む。

判定の材料（体力、疲労、日ごとの負荷）はダッシュボードと同じ計算から取る。チャートの
数字とアバターの話す数字を食い違わせないため。
"""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.fallback_review import fallback_review
from app.domain.load import FitnessPoint
from app.domain.review_week import review_period
from app.domain.situation import (
    DAYS_IN_WEEK,
    PreviousWeek,
    Situation,
    WeekInput,
    WeekSituation,
    judge_week,
)
from app.models import ReviewStatus, User, WeeklyReview, WeeklyReviewOption, Workout
from app.schemas.dashboard import DayPoint
from app.schemas.reviews import ReviewOptionOut, WeeklyReviewOut
from app.services.dashboard import build_dashboard


class HeartRateSettingsMissingError(Exception):
    """最大心拍か安静時心拍が未設定。負荷が出ないので、状況を判定できない。"""


def _start_of(day: date, tz: ZoneInfo) -> datetime:
    return datetime.combine(day, time.min, tzinfo=tz)


def _point(p: DayPoint) -> FitnessPoint:
    # 余力は判定の側で体力 − 疲労から計算し直すので、ここではそのまま写す
    return FitnessPoint(
        day=p.day, load=p.load, fitness=p.fitness, fatigue=p.fatigue, headroom=p.headroom
    )


async def judge_review_week(session: AsyncSession, user: User, start: date) -> WeekSituation:
    """start から 7 日間の状況を判定する。前の週の数字も一緒に読む。"""
    if user.max_heart_rate is None or user.resting_heart_rate is None:
        raise HeartRateSettingsMissingError
    tz = ZoneInfo(user.timezone)
    end = start + timedelta(days=DAYS_IN_WEEK - 1)
    previous_start = start - timedelta(days=DAYS_IN_WEEK)

    first_at, last_before_at = (
        await session.execute(
            select(
                func.min(Workout.started_at),
                func.max(Workout.started_at).filter(Workout.started_at < _start_of(start, tz)),
            ).where(Workout.user_id == user.id)
        )
    ).one()
    durations = await session.execute(
        select(Workout.started_at, Workout.duration_sec).where(
            Workout.user_id == user.id,
            Workout.started_at >= _start_of(previous_start, tz),
            Workout.started_at < _start_of(end + timedelta(days=1), tz),
        )
    )
    # その週と前の週の、ワークアウト 1 件に 1 つの日付と時間
    sessions = [(at.astimezone(tz).date(), sec) for at, sec in durations]
    this_week = [(day, sec) for day, sec in sessions if day >= start]
    last_week = [(day, sec) for day, sec in sessions if day < start]

    dashboard = await build_dashboard(session, user, since=previous_start, until=end, sport="all")
    days = {p.day: p for p in dashboard.days}
    last_before = None if last_before_at is None else last_before_at.astimezone(tz).date()

    return judge_week(
        WeekInput(
            start=start,
            first_workout_day=None if first_at is None else first_at.astimezone(tz).date(),
            last_workout_day_before=last_before,
            workout_days=[day for day, _ in this_week],
            total_sec=sum(sec for _, sec in this_week),
            # 負荷が分からない日は、心拍のないワークアウトを含む日
            unknown_load_days=sum(1 for day in {d for d, _ in this_week} if days[day].load is None),
            end=_point(days[end]),
            # それより前に記録がなければ、前の週と比べるものはない
            previous=None
            if last_before is None
            else PreviousWeek(
                workouts=len(last_week),
                total_sec=sum(sec for _, sec in last_week),
                end=_point(days[start - timedelta(days=1)]),
            ),
        )
    )


async def _options(session: AsyncSession, review_id: int) -> list[WeeklyReviewOption]:
    stmt = (
        select(WeeklyReviewOption)
        .where(WeeklyReviewOption.weekly_review_id == review_id)
        .order_by(WeeklyReviewOption.position)
    )
    return list(await session.scalars(stmt))


async def _out(session: AsyncSession, review: WeeklyReview) -> WeeklyReviewOut:
    options = await _options(session, review.id)
    return WeeklyReviewOut(
        id=review.id,
        period_start=review.period_start,
        period_end=review.period_end,
        situation=Situation(review.situation),
        script=review.script,
        status=ReviewStatus(review.status),
        is_fallback=review.is_fallback,
        created_at=review.created_at,
        options=[ReviewOptionOut.model_validate(o) for o in options],
    )


async def create_review(
    session: AsyncSession, user: User, today: date | None = None
) -> tuple[WeeklyReviewOut, bool]:
    """今の振り返りの週の振り返りを、定型で作る。作ったら True、もうあればそれと False。

    週は、今日以前でいちばん近い振り返りの曜日の前日までの 7 日間（利用者のタイムゾーン）。
    同時に 2 回呼ばれても 1 件だけ入る（ON CONFLICT DO NOTHING）。振り返りと選択肢は
    同じトランザクションで入れるので、後から来た側には選択肢までそろって見える。
    """
    today = today or datetime.now(ZoneInfo(user.timezone)).date()
    start, end = review_period(today, user.review_weekday)
    existing = await _find(session, user.id, start)
    if existing is not None:
        return await _out(session, existing), False

    week = await judge_review_week(session, user, start)
    content = fallback_review(week)
    review = await session.scalar(
        insert(WeeklyReview)
        .values(
            user_id=user.id,
            period_start=start,
            period_end=end,
            situation=week.situation.value,
            script=content.script,
            status=ReviewStatus.COMPLETED.value,
            is_fallback=True,
        )
        .on_conflict_do_nothing(index_elements=[WeeklyReview.user_id, WeeklyReview.period_start])
        .returning(WeeklyReview)
    )
    if review is None:
        # 判定のあいだに、別の呼び出しが同じ週を入れた。その行は相手の commit の後に見える
        raced = await _find(session, user.id, start)
        if raced is None:
            raise RuntimeError("weekly review conflicted but was not found")
        return await _out(session, raced), False

    session.add_all(
        WeeklyReviewOption(
            weekly_review_id=review.id,
            position=i,
            label=o.label,
            description=o.description,
        )
        for i, o in enumerate(content.options)
    )
    await session.commit()
    return await _out(session, review), True


async def _find(session: AsyncSession, user_id: int, start: date) -> WeeklyReview | None:
    return await session.scalar(
        select(WeeklyReview).where(
            WeeklyReview.user_id == user_id, WeeklyReview.period_start == start
        )
    )


async def latest_review(session: AsyncSession, user_id: int) -> WeeklyReviewOut | None:
    """本人のいちばん新しい期間の振り返り。まだなければ None。"""
    review = await session.scalar(
        select(WeeklyReview)
        .where(WeeklyReview.user_id == user_id)
        .order_by(WeeklyReview.period_start.desc())
        .limit(1)
    )
    return None if review is None else await _out(session, review)
