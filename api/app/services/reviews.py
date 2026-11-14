"""週次レビューを作る、読む。

判定の材料（体力、疲労、日ごとの負荷）はダッシュボードと同じ計算から取る。チャートの
数字とアバターの話す数字を食い違わせないため。
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.calendar import start_of_day, today_for
from app.domain.expression import DEFAULT_EXPRESSION, Expression, expression_for
from app.domain.fallback_review import ReviewContent, ReviewOption, fallback_review
from app.domain.line_check import LineCheck, flagged
from app.domain.load import FitnessPoint
from app.domain.note_check import NoteCheck, health_flag
from app.domain.review_material import ReviewMaterial
from app.domain.review_prompt import NoteForReview, may_offer_more, review_prompt
from app.domain.review_week import review_period
from app.domain.situation import (
    DAYS_IN_WEEK,
    PreviousWeek,
    Situation,
    WeekInput,
    WeekSituation,
    judge_week,
)
from app.models import Note, ReviewStatus, User, WeeklyReview, WeeklyReviewOption, Workout
from app.schemas.dashboard import DayPoint
from app.schemas.reviews import ReviewOptionOut, WeeklyReviewOut
from app.services.audio import AudioStore, Voice, review_audio_path
from app.services.dashboard import build_dashboard

logger = logging.getLogger(__name__)


class ReviewWriter(Protocol):
    """LLM で週次レビューを書く。書けなければ None（定型に切り替える）。
    adapter の Gemini が実体。
    """

    async def write(self, contents: str) -> ReviewContent | None: ...


class LineChecker(Protocol):
    """LLM が書いたセリフを話してよいか、メモが痛みや病気に触れているかを確かめる。
    確かめられなければ None。adapter の Jev が実体。"""

    async def check(self, content: ReviewContent) -> LineCheck | None: ...

    async def check_notes(self, notes: Sequence[NoteForReview]) -> NoteCheck | None: ...


class HeartRateSettingsMissingError(Exception):
    """最大心拍、安静時心拍、強度の境目 2 つのどれかが未設定。

    心拍の 2 つがなければ負荷が出ず、状況を判定できない。境目がなければ強度ごとの時間が
    出ず、強度の配分を判定できない。どちらも週次レビューの材料なので、4 つそろうまで作らない。
    """


class ReviewNotFoundError(Exception):
    """その利用者の週次レビューに、その id がない。
    選択肢がその週次レビューのものでない場合も含む。
    """


class ReviewClosedError(Exception):
    """今の週の週次レビューではない。過ぎた週の選択は、次の週の材料に使った後なので変えない。"""


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
    if (
        user.max_heart_rate is None
        or user.resting_heart_rate is None
        or user.zone_boundary_1 is None
        or user.zone_boundary_2 is None
    ):
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

    dashboard = await build_dashboard(session, user, since=previous_start, until=end, today=today)
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
    """start から 7 日間の週次レビューを作る材料。判定と、ちょうど 1 週前の回で選んだ選択肢。

    1 週前は start の 7 日前に始まる回だけを見る。間が空いた後や、週次レビューの曜日を変えた
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


async def notes_for_review(
    session: AsyncSession, user: User, start: date, end: date
) -> list[NoteForReview]:
    """start〜end のメモ。「メモを AI に送らない」設定なら、読まずに空を返す。"""
    if not user.send_notes_to_ai:
        return []
    rows = await session.execute(
        select(Note.date, Note.label, Note.body)
        .where(Note.user_id == user.id, Note.date >= start, Note.date <= end)
        .order_by(Note.date)
    )
    return [NoteForReview(day=r.date, label=r.label, body=r.body) for r in rows]


@dataclass(frozen=True)
class _Written:
    """_write の結果。content は話してよいと確かめられた LLM の文（なければ定型にする）。

    expression は content に合う表情。content がなければ使わない（定型は relaxed）。
    """

    content: ReviewContent | None
    health_flag: bool
    expression: Expression = DEFAULT_EXPRESSION


async def _write(
    session: AsyncSession,
    user: User,
    material: ReviewMaterial,
    writer: ReviewWriter | None,
    checker: LineChecker | None,
) -> _Written:
    """メモを Jev で確かめて体調のフラグを決め、LLM に書いてもらい、Jev で確かめる。
    話してよいと確かめられた文と、体調のフラグと、文に合う表情を返す。

    文は、writer がない（設定で切っている）、書けない、確かめて引っかかった、確かめられ
    なかった、のどれでも None（定型にする）。checker がなければ、確かめられない文を書かせても
    話さないので、LLM も呼ばない。メモも送らずに済む。

    フラグは writer の有無に関わらず、checker があれば決める。LLM に書かせる前に、その週の
    メモが痛みや病気に触れているかを Jev で確かめ、コードで決める。フラグが立てば、LLM にも
    定型にも量や強度を上げる選択肢を出させない。メモを確かめられなければ LLM は呼ばず、
    フラグを立てた側（安全側）にして定型にする。メモを読んでいない（checker がない、送らない
    設定、メモがない）ときは立てない。

    増やす選択肢を出してはいけない週（状況とフラグからコードで決める）は、LLM の文が
    増やすことを勧めていれば、押し付けない提案でも引っかけて定型にする。
    """
    if checker is None:
        if writer is not None:
            logger.warning(
                "review: no line checker, so not asking the writer; "
                "falling back to the fixed script for user %s",
                user.id,
            )
        return _Written(None, False)
    week = material.week
    notes = await notes_for_review(session, user, week.start, week.end)
    # LLM と Jev を待つ 10〜90 秒のあいだ、読み込みのトランザクションを閉じて DB の接続を
    # 手放す。読んだだけなので何も書かない。expire_on_commit=False なので、読んだ行はそのまま使える
    await session.commit()
    flag = False
    if notes:
        note_check = await checker.check_notes(notes)
        if note_check is None:
            logger.warning(
                "review: could not check the notes; falling back to the fixed script for user %s",
                user.id,
            )
            return _Written(None, True)
        flag = health_flag(note_check)
        if flag:
            logger.info(
                # メモの文は残さない
                "review: the notes mention pain or sickness (mentions_health=%.2f); "
                "not offering more load for user %s",
                note_check.mentions_health,
                user.id,
            )
    if writer is None:
        return _Written(None, flag)
    content = await writer.write(review_prompt(material, notes, health_flag=flag))
    if content is None:
        logger.warning(
            "review: the writer could not write; falling back to the fixed script for user %s",
            user.id,
        )
        return _Written(None, flag)
    check = await checker.check(content)
    if check is None:
        logger.warning(
            "review: could not check the line; falling back to the fixed script for user %s",
            user.id,
        )
        return _Written(None, flag)
    if risks := flagged(check, may_offer_more(week.situation, flag)):
        logger.warning(
            "review: the line was flagged (%s); falling back to the fixed script for user %s",
            # 境目ぎりぎりか、はっきり「はい」かを見分けられるように確率も残す。セリフは残さない
            ", ".join(f"{name}={yes:.2f}" for name, yes in risks.items()),
            user.id,
        )
        return _Written(None, flag)
    return _Written(content, flag, expression_for(check.expression))


async def _options(session: AsyncSession, review_id: int) -> list[WeeklyReviewOption]:
    stmt = (
        select(WeeklyReviewOption)
        .where(WeeklyReviewOption.weekly_review_id == review_id)
        .order_by(WeeklyReviewOption.position)
    )
    return list(await session.scalars(stmt))


async def _audio_url(review: WeeklyReview, audio: AudioStore | None) -> str | None:
    """音声を再生できる URL。音声がない、置き場所の設定がない、署名できないなら None。"""
    if review.audio_path is None or audio is None:
        return None
    return await audio.url(review.audio_path)


async def _out(
    session: AsyncSession, review: WeeklyReview, audio: AudioStore | None
) -> WeeklyReviewOut:
    """応答の形にする。音声があり、audio があれば、再生できる URL を付ける。"""
    options = await _options(session, review.id)
    audio_url = await _audio_url(review, audio)
    return WeeklyReviewOut(
        id=review.id,
        period_start=review.period_start,
        period_end=review.period_end,
        situation=Situation(review.situation),
        script=review.script,
        status=ReviewStatus(review.status),
        is_fallback=review.is_fallback,
        expression=Expression(review.expression),
        created_at=review.created_at,
        audio_url=audio_url,
        options=[ReviewOptionOut.model_validate(o) for o in options],
    )


async def _speak(
    session: AsyncSession,
    user: User,
    script: str,
    voice: Voice | None,
    audio: AudioStore | None,
) -> bytes | None:
    """セリフを声にする。voice と audio のどちらかがない（設定で切っている）、または
    読めなければ None（音声なしで作る）。"""
    if voice is None or audio is None:
        return None
    # 読み上げを待つ 10〜45 秒のあいだ、DB の接続を手放す
    await session.commit()
    wav = await voice.speak(script)
    if wav is None:
        logger.warning(
            "review: could not voice the script; saving it without audio for user %s", user.id
        )
    return wav


async def create_review(
    session: AsyncSession,
    user: User,
    writer: ReviewWriter | None = None,
    checker: LineChecker | None = None,
    today: date | None = None,
    *,
    voice: Voice | None = None,
    audio: AudioStore | None = None,
) -> tuple[WeeklyReviewOut, bool]:
    """今の週の週次レビューを作る。作ったら True、もうあればそれと False。

    writer と checker の両方があれば LLM に書いてもらい、Jev で話してよいと確かめられた
    ときだけその文で作る。それ以外（どちらかがない、書けない、引っかかった、確かめられ
    なかった）は定型で作る。

    voice と audio の両方があれば、決まったセリフ（LLM の文でも定型でも）を声にして置く。
    読めない、置けないときは音声なし（audio_url が null）で作り、文字だけで見せる。

    週は、今日以前でいちばん近い週次レビューの曜日の前日までの 7 日間（利用者のタイムゾーン）。
    一度作った週は作り直さない。作った時点の記録で書いた、その週の 1 通にする。選択肢を
    選んだ後にセリフが変わると選んだ理由とずれ、LLM で作るようになれば作り直すたびに
    費用もかかるため。遅れて届く記録は、自動で作る時刻を遅らせて拾う。
    同時に 2 回呼ばれても 1 件だけ入る（ON CONFLICT DO NOTHING）。そのときは LLM も
    2 回呼ばれるが、残るのは先に入れた側。週次レビューと選択肢は同じトランザクションで
    入れるので、後から来た側には選択肢までそろって見える。
    """
    today = today or today_for(user.timezone)
    start, end = review_period(today, user.review_weekday)
    existing = await _find(session, user.id, start)
    if existing is not None:
        return await _out(session, existing, audio), False

    material = await review_material(session, user, start, today)
    written = await _write(session, user, material, writer, checker)
    # 定型は前の週の選択とメモを読まない。メモを Jev で確かめたフラグだけを使う。
    # 定型のときの表情は relaxed（_Written の既定）
    content = written.content or fallback_review(material.week, written.health_flag)
    wav = await _speak(session, user, content.script, voice, audio)
    review = await session.scalar(
        insert(WeeklyReview)
        .values(
            user_id=user.id,
            period_start=start,
            period_end=end,
            situation=material.week.situation.value,
            script=content.script,
            status=ReviewStatus.COMPLETED.value,
            is_fallback=written.content is None,
            expression=written.expression.value,
        )
        .on_conflict_do_nothing(index_elements=[WeeklyReview.user_id, WeeklyReview.period_start])
        .returning(WeeklyReview)
    )
    if review is None:
        # 判定のあいだに、別の呼び出しが同じ週を入れた。その行は相手の commit の後に見える
        raced = await _find(session, user.id, start)
        if raced is None:
            raise RuntimeError("weekly review conflicted but was not found")
        return await _out(session, raced, audio), False

    if wav is not None and audio is not None:
        # 置き場所に週次レビューの id を使うので、行を入れてから置く。置いてから commit に
        # 失敗したときに残るファイルも、利用者ごとの場所にあるので、アカウントを消せば消える
        path = review_audio_path(user.id, review.id)
        if await audio.put(path, wav):
            review.audio_path = path
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
    return await _out(session, review, audio), True


async def _find(session: AsyncSession, user_id: int, start: date) -> WeeklyReview | None:
    return await session.scalar(
        select(WeeklyReview).where(
            WeeklyReview.user_id == user_id, WeeklyReview.period_start == start
        )
    )


async def current_review(
    session: AsyncSession,
    user: User,
    today: date | None = None,
    *,
    audio: AudioStore | None = None,
) -> WeeklyReviewOut | None:
    """今の週の週次レビュー。週の決め方は create_review と同じ。まだなければ None。

    いちばん新しい期間の行ではなく、今の週で探す。週次レビューの曜日を変えた直後は、
    いちばん新しい行が今の週より古い回のことがあるため。

    デモの利用者だけは、いちばん新しい期間の行を返す。デモデータは日付が動かないので、
    今の週で探すといつも None になるため。行は seed で入れる。
    """
    if user.is_demo:
        latest = await session.scalar(
            select(WeeklyReview)
            .where(WeeklyReview.user_id == user.id)
            .order_by(WeeklyReview.period_start.desc())
            .limit(1)
        )
        return None if latest is None else await _out(session, latest, audio)
    today = today or today_for(user.timezone)
    start, _ = review_period(today, user.review_weekday)
    review = await _find(session, user.id, start)
    return None if review is None else await _out(session, review, audio)


async def select_option(
    session: AsyncSession,
    user: User,
    review_id: int,
    option_id: int,
    today: date | None = None,
    *,
    audio: AudioStore | None = None,
) -> WeeklyReviewOut:
    """週次レビューの選択肢を 1 つ選ぶ。もう別のものを選んでいれば、そちらを外して選び直す。

    選び直せるのは今の週の週次レビューだけ。同じものをもう一度選んだときは、最初に選んだ
    時刻のまま返す。週次レビューの行を FOR UPDATE で押さえ、同時に 2 つ選ばれても 1 つだけ残す。
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
        # 1 つの週次レビューで選べるのは 1 つだけ（部分ユニーク索引）。先に外してから入れる
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
    # 選び直した行だけが新しく、自分の行は古いまま残り、選択済みが 2 つに見える。
    # 音声の URL は commit の後に付ける。署名（IAM に頼む）を待つあいだ、ロックを持たない
    out = await _out(session, review, None)
    await session.commit()
    return out.model_copy(update={"audio_url": await _audio_url(review, audio)})
