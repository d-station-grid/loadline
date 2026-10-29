"""週に 1 回の振り返りを作る、読む。

判定の材料（体力、疲労、日ごとの負荷）はダッシュボードと同じ計算から取る。チャートの
数字とアバターの話す数字を食い違わせないため。
"""

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.calendar import start_of_day, today_for
from app.domain.fallback_review import ReviewOption, fallback_review
from app.domain.load import FitnessPoint
from app.domain.review_material import ReviewMaterial
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


class ReviewNotFoundError(Exception):
    """その利用者の振り返りに、その id がない。選択肢がその振り返りのものでない場合も含む。"""


class ReviewClosedError(Exception):
    """今の週の振り返りではない。過ぎた週の選択は、次の週の材料に使った後なので変えない。"""


def _point(p: DayPoint) -> FitnessPoint:
    # 余力は判定の側で体力 − 疲労から計算し直すので、ここではそのまま写す
    return FitnessPoint(
        day=p.day, load=p.load, fitness=p.fitness, fatigue=p.fatigue, headroom=p.headroom
    )


async def judge_review_week(
    session: AsyncSession, user: User, start: date, today: date
) -> WeekSituation:
    """start から 7 日間の状況を判定する。前の週の数字も一緒に読む。

    today は利用者のタイムゾーンでの今日。週は今日より前に終わっていなければならない。
    ダッシュボードの計算は今日で切るので、終わっていない週では最終日の値がない。
    """
    if user.max_heart_rate is None or user.resting_heart_rate is None:
        raise HeartRateSettingsMissingError
    tz = ZoneInfo(user.timezone)
    end = start + timedelta(days=DAYS_IN_WEEK - 1)
    if end >= today:
        raise ValueError(f"the week must end before today ({today}), got {end}")
    previous_start = start - timedelta(days=DAYS_IN_WEEK)

    first_at, last_before_at = (
        await session.execute(
            select(
                func.min(Workout.started_at),
                func.max(Workout.started_at).filter(Workout.started_at < start_of_day(start, tz)),
            ).where(Workout.user_id == user.id)
        )
    ).one()
    durations = await session.execute(
        select(Workout.started_at, Workout.duration_sec).where(
            Workout.user_id == user.id,
            Workout.started_at >= start_of_day(previous_start, tz),
            Workout.started_at < start_of_day(end + timedelta(days=1), tz),
        )
    )
    # その週と前の週の、ワークアウト 1 件に 1 つの日付と時間
    sessions = [(at.astimezone(tz).date(), sec) for at, sec in durations]
    this_week = [(day, sec) for day, sec in sessions if day >= start]
    last_week = [(day, sec) for day, sec in sessions if day < start]

    dashboard = await build_dashboard(
        session, user, since=previous_start, until=end, sport="all", today=today
    )
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


async def review_material(
    session: AsyncSession, user: User, start: date, today: date
) -> ReviewMaterial:
    """start から 7 日間の振り返りを作る材料。判定と、ちょうど 1 週前の回で選んだ選択肢。

    1 週前は start の 7 日前に始まる回だけを見る。間が空いた後や、振り返りの曜日を変えた
    直後は、前の回の選択が今の週と離れているので渡さない。
    """
    week = await judge_review_week(session, user, start, today)
    chosen = (
        await session.execute(
            select(WeeklyReviewOption.label, WeeklyReviewOption.description)
            .join(WeeklyReview, WeeklyReview.id == WeeklyReviewOption.weekly_review_id)
            .where(
                WeeklyReview.user_id == user.id,
                WeeklyReview.period_start == start - timedelta(days=DAYS_IN_WEEK),
                WeeklyReviewOption.selected_at.is_not(None),
            )
        )
    ).one_or_none()
    return ReviewMaterial(
        week=week,
        previous_choice=None if chosen is None else ReviewOption(chosen.label, chosen.description),
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
    一度作った週は作り直さない。作った時点の記録で書いた、その週の 1 通にする。選択肢を
    選んだ後にセリフが変わると選んだ理由とずれ、LLM で作るようになれば作り直すたびに
    費用もかかるため。遅れて届く記録は、自動で作る時刻を遅らせて拾う。
    同時に 2 回呼ばれても 1 件だけ入る（ON CONFLICT DO NOTHING）。振り返りと選択肢は
    同じトランザクションで入れるので、後から来た側には選択肢までそろって見える。
    """
    today = today or today_for(user.timezone)
    start, end = review_period(today, user.review_weekday)
    existing = await _find(session, user.id, start)
    if existing is not None:
        return await _out(session, existing), False

    material = await review_material(session, user, start, today)
    # 定型は前の週の選択を読まない。材料は LLM で作るときのためにそろえておく
    content = fallback_review(material.week)
    review = await session.scalar(
        insert(WeeklyReview)
        .values(
            user_id=user.id,
            period_start=start,
            period_end=end,
            situation=material.week.situation.value,
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


async def current_review(
    session: AsyncSession, user: User, today: date | None = None
) -> WeeklyReviewOut | None:
    """今の振り返りの週の振り返り。週の決め方は create_review と同じ。まだなければ None。

    いちばん新しい期間の行ではなく、今の週で探す。振り返りの曜日を変えた直後は、
    いちばん新しい行が今の週より古い回のことがあるため。
    """
    today = today or today_for(user.timezone)
    start, _ = review_period(today, user.review_weekday)
    review = await _find(session, user.id, start)
    return None if review is None else await _out(session, review)


async def select_option(
    session: AsyncSession, user: User, review_id: int, option_id: int, today: date | None = None
) -> WeeklyReviewOut:
    """振り返りの選択肢を 1 つ選ぶ。もう別のものを選んでいれば、そちらを外して選び直す。

    選び直せるのは今の週の振り返りだけ。同じものをもう一度選んだときは、最初に選んだ
    時刻のまま返す。振り返りの行を FOR UPDATE で押さえ、同時に 2 つ選ばれても 1 つだけ残す。
    応答は、そのリクエストで選んだ時点の状態。
    """
    review = await session.scalar(
        select(WeeklyReview)
        .where(WeeklyReview.id == review_id, WeeklyReview.user_id == user.id)
        .with_for_update()
    )
    if review is None:
        raise ReviewNotFoundError
    option = await session.scalar(
        select(WeeklyReviewOption).where(
            WeeklyReviewOption.id == option_id,
            WeeklyReviewOption.weekly_review_id == review.id,
        )
    )
    if option is None:
        raise ReviewNotFoundError

    today = today or today_for(user.timezone)
    start, _ = review_period(today, user.review_weekday)
    if review.period_start != start:
        raise ReviewClosedError

    if option.selected_at is None:
        # 1 つの振り返りで選べるのは 1 つだけ（部分ユニーク索引）。先に外してから入れる
        await session.execute(
            update(WeeklyReviewOption)
            .where(
                WeeklyReviewOption.weekly_review_id == review.id,
                WeeklyReviewOption.selected_at.is_not(None),
            )
            .values(selected_at=None)
        )
        await session.execute(
            update(WeeklyReviewOption)
            .where(WeeklyReviewOption.id == option.id)
            .values(selected_at=datetime.now(UTC))
        )
    # 応答はロックを持ったまま組み立てる。commit の後に読むと、その間に別のリクエストが
    # 選び直した行だけが新しく、自分の行は古いまま残り、選択済みが 2 つに見える
    out = await _out(session, review)
    await session.commit()
    return out
