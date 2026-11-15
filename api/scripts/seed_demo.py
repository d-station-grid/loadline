"""ゲストに見せるデモデータを入れる。何度流しても同じ中身になる。

使い方（api/ で）:
  uv run python -m scripts.seed_demo

声も入れるとき（TTS_URL と AUDIO_BUCKET を設定して）。手元の Google アカウントの
資格情報からは tts の ID トークンを作れないので、gcloud で取って渡す:
  TTS_ID_TOKEN=$(gcloud auth print-identity-token --project loadline-app) \
    uv run python -m scripts.seed_demo

日本語の声（GOOGLE_TTS_MODEL）も入れるとき。手元の Google アカウントの資格情報で
Cloud Text-to-Speech を呼ぶには、割り当てのプロジェクトが要る:
  GOOGLE_TTS_MODEL=gemini-2.5-pro-tts GOOGLE_TTS_QUOTA_PROJECT=loadline-app \
    TTS_ID_TOKEN=... uv run python -m scripts.seed_demo

デモの利用者（is_demo、firebase_uid は NULL）は言語ごとに 1 人（英語と日本語）。どちらも
消して作り直し、16 週分のワークアウトと心拍、VO2max、メモを入れる。記録は決まった乱数で
作るので、毎回同じになり、英語と日本語で同じ記録になる。メモは言語ごとに書いてある。
日付も動かさない。ゲストのダッシュボードは最後のワークアウトの日を今日として切る。

週次レビューは、利用者と同じ create_review で、言語ごとに最後の 4 週分を作る。数字の判定はコードで
するので、チャートとセリフの数字が食い違わない。GEMINI_PROJECT と TYPESAFE_API_KEY が
あれば Gemini が書いて Jev で確かめ、なければ定型になる。前の 3 週は選択肢を 1 つ
選んでおく。最後の週は選ばずに残す（ゲストには押せない選択肢として見せる）。
TTS_URL と AUDIO_BUCKET があれば、利用者と同じく週次レビューのセリフを声にして置く。

全体を 1 つのトランザクションで入れる。途中で失敗したら何も変えず、前のデモデータが
そのまま残る。同時に 2 回流しても、advisory lock で 1 回ずつ順に入る。

デモの利用者は作り直すたびに id が変わり、音声の置き場所（users/{id}/）も変わる。前の
デモの音声は、新しいデモを確定してから消す。失敗したときは、新しく置いた音声を消す。
"""

import asyncio
import logging
import os
import random
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.adapters.audio_storage import audio_store
from app.adapters.gemini import gemini_writer
from app.adapters.google_tts import google_voice
from app.adapters.jev import jev_checker
from app.adapters.tts import kokoro_voice
from app.core.config import get_settings
from app.core.db import get_engine
from app.domain.language import Language
from app.models import Note, User, Vo2maxReading, WeeklyReview, Workout, WorkoutHeartRate
from app.services.audio import AudioStore, Voice, user_audio_prefix, voices
from app.services.reviews import LineChecker, ReviewWriter, create_review, select_option

logger = logging.getLogger(__name__)

DEMO_EMAILS = {Language.EN: "demo@loadline.invalid", Language.JA: "demo-ja@loadline.invalid"}
TIMEZONE = "Asia/Tokyo"
# 最後の記録の日（日曜）。週次レビューの曜日は月曜なので、最後の回はこの日までの 7 日間になる
LAST_DAY = date(2026, 11, 1)
WEEKS = 16
FIRST_DAY = LAST_DAY - timedelta(weeks=WEEKS) + timedelta(days=1)
REVIEW_WEEKDAY = 0  # 月曜
REVIEWS = 4

MAX_HR = 188
RESTING_HR = 52
ZONE_1 = 140  # Low と Mid の境目
ZONE_2 = 160  # Mid と High の境目

# 外部 id を毎回同じにするための名前空間
_NAMESPACE = uuid.UUID("6f1b0d6e-45de-4c0a-9d6b-6c6f61646c6e")
# デモデータを入れる間の advisory lock の鍵。ほかで使わない数ならよい
_LOCK_KEY = 45_0001


@dataclass(frozen=True)
class Planned:
    """1 回のワークアウトの予定。kind は心拍の形。"""

    sport: str  # ride か run
    start: time
    minutes: int
    kind: str  # easy、steady、intervals


# 曜日（0 が月曜）ごとの、ふだんの週の予定。月曜と金曜は休み
_WEEK_PLAN: dict[int, Planned] = {
    1: Planned("run", time(6, 30), 40, "steady"),
    2: Planned("ride", time(19, 0), 60, "easy"),
    3: Planned("run", time(6, 30), 45, "intervals"),
    5: Planned("ride", time(8, 0), 120, "steady"),
    6: Planned("run", time(7, 0), 60, "easy"),
}

# 何週目（0 から）の量の倍率。少しずつ増やし、4 週ごとに軽くする。9 週目は風邪で休む
_WEEK_SCALE = [0.8, 0.9, 1.0, 0.7, 0.9, 1.0, 1.1, 0.8, 1.0, 0.0, 0.6, 0.9, 1.1, 1.2, 0.9, 1.0]

# 9 週目は風邪。最後の日に軽く走るだけ
_SICK_WEEK = 9
# 14 週目の土曜はレース（10k）
_RACE_DAY = FIRST_DAY + timedelta(weeks=14, days=5)

# メモ。日付は最初の日からの日数。ラベルはチャートに出る
_NOTES_EN: list[tuple[int, str | None, str]] = [
    (5, None, "First long ride of the summer. Hot, drank a lot."),
    (17, "New shoes", "Tried the new running shoes. A bit stiff for the first 2 km."),
    (33, None, "Legs felt heavy on the intervals. Slept badly the night before."),
    (47, "Hill ride", "Rode the hill route with friends. Hard but fun."),
    (63, "Cold", "Caught a cold. Taking the week off."),
    (69, None, "Still coughing a little, so just an easy jog."),
    (80, None, "Back to normal. Kept everything easy this week."),
    (_RACE_DAY.toordinal() - FIRST_DAY.toordinal(), "10k race", "10k race. Finished in 47:30!"),
    (WEEKS * 7 - 2, None, "Easy week after the race. Body feels fresh."),
]

# 日本語のデモのメモ。日付とラベルの有無は英語と同じ。ラベルは全角 6 文字まで
_NOTES_JA: list[tuple[int, str | None, str]] = [
    (5, None, "夏の初めてのロングライド。暑くて、水をたくさん飲んだ。"),
    (17, "新シューズ", "新しいランニングシューズを試した。最初の2kmは少し硬かった。"),
    (33, None, "インターバルで脚が重かった。前の晩はよく眠れなかった。"),
    (47, "坂のライド", "友だちと坂のコースを走った。きつかったけど楽しかった。"),
    (63, "風邪", "風邪をひいた。今週は休む。"),
    (69, None, "まだ少し咳が出るので、軽いジョグだけ。"),
    (80, None, "いつもの調子に戻った。今週は全部軽めにした。"),
    (_RACE_DAY.toordinal() - FIRST_DAY.toordinal(), "10kmレース", "10kmレース。47分30秒で完走！"),
    (WEEKS * 7 - 2, None, "レースのあとの軽い週。体が軽い。"),
]

_NOTES = {Language.EN: _NOTES_EN, Language.JA: _NOTES_JA}


def _heart_rates(rng: random.Random, kind: str, minutes: int) -> list[int]:
    """1 分ごとの平均心拍。最初の数分は上がっていく途中。"""
    targets = {"easy": 128, "steady": 146}
    bpms = []
    for m in range(minutes):
        if kind == "intervals":
            # 10 分のアップのあと、4 分強く 3 分ゆるく
            target = 130 if m < 10 or (m - 10) % 7 >= 4 else 168
        else:
            target = targets[kind]
        warmup = max(0.0, 1 - m / 6)
        bpm = target - warmup * (target - 95) + rng.gauss(0, 3)
        bpms.append(round(min(MAX_HR - 2, bpm)))
    return bpms


def _plan(day: date, week: int) -> Planned | None:
    """その日のワークアウト。なければ None。"""
    if week == _SICK_WEEK:
        # 風邪の週は最後の日に短く走るだけ
        return Planned("run", time(7, 0), 20, "easy") if day.weekday() == 6 else None
    if day == _RACE_DAY:
        return Planned("run", time(8, 0), 48, "intervals")
    planned = _WEEK_PLAN.get(day.weekday())
    if planned is None:
        return None
    minutes = round(planned.minutes * _WEEK_SCALE[week] / 5) * 5
    return Planned(planned.sport, planned.start, max(minutes, 20), planned.kind)


def _workouts(user_id: int, rng: random.Random) -> list[tuple[Workout, list[int]]]:
    tz = ZoneInfo(TIMEZONE)
    rows = []
    for offset in range(WEEKS * 7):
        day = FIRST_DAY + timedelta(days=offset)
        planned = _plan(day, offset // 7)
        if planned is None:
            continue
        started = datetime.combine(day, planned.start, tz).astimezone(UTC)
        bpms = _heart_rates(rng, planned.kind, planned.minutes)
        workout = Workout(
            user_id=user_id,
            external_id=str(uuid.uuid5(_NAMESPACE, f"workout-{day.isoformat()}")).upper(),
            sport=planned.sport,
            started_at=started,
            ended_at=started + timedelta(minutes=planned.minutes),
            duration_sec=planned.minutes * 60,
            avg_heart_rate=round(sum(bpms) / len(bpms)),
            max_heart_rate=max(bpms) + 2,
        )
        rows.append((workout, bpms))
    return rows


def _vo2max(user_id: int, rng: random.Random) -> list[Vo2maxReading]:
    """日曜ごとの VO2max。少しずつ上がり、風邪の週のあとで少し下がる。"""
    tz = ZoneInfo(TIMEZONE)
    readings = []
    for week in range(WEEKS):
        day = FIRST_DAY + timedelta(weeks=week, days=6)
        value = 44.0 + week * 0.22 - (0.8 if week in (_SICK_WEEK, _SICK_WEEK + 1) else 0)
        value += rng.uniform(-0.2, 0.2)
        readings.append(
            Vo2maxReading(
                user_id=user_id,
                measured_at=datetime.combine(day, time(9, 0), tz).astimezone(UTC),
                value=Decimal(f"{value:.1f}"),
            )
        )
    return readings


async def seed_demo(
    session: AsyncSession,
    writer: ReviewWriter | None = None,
    checker: LineChecker | None = None,
    *,
    voice: Voice | None = None,
    audio: AudioStore | None = None,
    language: Language = Language.EN,
) -> User:
    """その言語のデモの利用者を作り直して、記録、メモ、週次レビューを入れる。

    session は外のトランザクションに入れておく（seed_demo_atomically）。中の commit は
    savepoint になり、外のトランザクションを確定するまで、ほかからは前のデモが見える。
    """
    rng = random.Random(45)
    # 同時に流れたら、先のほうが確定するまで待つ。待たずに進むと両方がデモの利用者を作る
    await session.execute(select(func.pg_advisory_xact_lock(_LOCK_KEY)))
    # 行を消せば、外部キーの ON DELETE CASCADE で記録も週次レビューも消える
    await session.execute(
        delete(User).where(User.is_demo.is_(True), User.language == language.value)
    )
    user = User(
        email=DEMO_EMAILS[language],
        is_demo=True,
        language=language.value,
        max_heart_rate=MAX_HR,
        resting_heart_rate=RESTING_HR,
        zone_boundary_1=ZONE_1,
        zone_boundary_2=ZONE_2,
        timezone=TIMEZONE,
        review_weekday=REVIEW_WEEKDAY,
    )
    session.add(user)
    await session.flush()

    workouts = _workouts(user.id, rng)
    session.add_all(w for w, _ in workouts)
    await session.flush()
    session.add_all(
        WorkoutHeartRate(
            workout_id=w.id,
            recorded_at=w.started_at + timedelta(minutes=m),
            min_bpm=bpm - 3,
            avg_bpm=bpm,
            max_bpm=bpm + 3,
        )
        for w, bpms in workouts
        for m, bpm in enumerate(bpms)
    )
    session.add_all(_vo2max(user.id, rng))
    session.add_all(
        Note(user_id=user.id, date=FIRST_DAY + timedelta(days=d), label=label, body=body)
        for d, label, body in _NOTES[language]
    )
    await session.commit()

    # 週次レビューを作る日（月曜）。最後の回は LAST_DAY の翌日
    review_days = [LAST_DAY + timedelta(days=1) - timedelta(weeks=n) for n in range(REVIEWS)][::-1]
    for i, day in enumerate(review_days):
        review, _ = await create_review(
            session, user, writer, checker, today=day, voice=voice, audio=audio
        )
        if i < len(review_days) - 1:
            # 前の週は、その週の間に真ん中の選択肢を選んだことにする
            option = review.options[len(review.options) // 2]
            await select_option(session, user, review.id, option.id, today=day)
    return user


async def seed_demo_atomically(
    engine: AsyncEngine,
    writer: ReviewWriter | None = None,
    checker: LineChecker | None = None,
    *,
    voice: Voice | None = None,
    audio: AudioStore | None = None,
) -> list[int]:
    """英語と日本語の seed_demo を 1 つのトランザクションで流し、最後まで済んだときだけ
    確定する。

    create_review などは途中で commit するので、外のトランザクションに入れて savepoint に
    する。途中で例外が出たら全部を巻き戻し、前のデモデータを残す。作ったデモの利用者の id を
    言語の順（英語、日本語）に返す。

    audio があれば、確定してから前のデモの音声を消す。途中で失敗したら、新しく置いた音声を
    消す（前のデモの音声は、前のデモの行と一緒に残る）。
    """
    tracked = None if audio is None else _Tracked(audio)
    try:
        async with engine.connect() as conn, conn.begin():
            async with AsyncSession(
                bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
            ) as session:
                # seed_demo と同じ鍵。トランザクションの中なら同じ鍵を何度取ってもよい。
                # 先に取らないと、同時に流れた側が確定する前の id を読み落とす
                await session.execute(select(func.pg_advisory_xact_lock(_LOCK_KEY)))
                old_ids = list(await session.scalars(select(User.id).where(User.is_demo.is_(True))))
                users = [
                    await seed_demo(
                        session, writer, checker, voice=voice, audio=tracked, language=language
                    )
                    for language in Language
                ]
    except BaseException:
        if tracked is not None:
            # 1 つずつ、置いたファイルそのものを消す（名前を prefix として渡す）
            await _delete_audio(tracked, tracked.put_paths)
        raise
    if tracked is not None:
        await _delete_audio(tracked, [user_audio_prefix(i) for i in old_ids])
    return [user.id for user in users]


async def _delete_audio(audio: AudioStore, prefixes: list[str]) -> None:
    """デモの音声を消す。消せなくてもデモは使えるので、ログに残して続ける。"""
    for prefix in prefixes:
        try:
            await audio.delete_all(prefix)
        except Exception:
            logger.exception("seed: could not delete the demo audio under %s", prefix)


class _Tracked:
    """置いたファイルの名前を控える。seed が途中で失敗したときに、それだけを消すため。"""

    def __init__(self, store: AudioStore) -> None:
        self._store = store
        self.put_paths: list[str] = []

    async def put(self, path: str, data: bytes, content_type: str) -> bool:
        saved = await self._store.put(path, data, content_type)
        if saved:
            self.put_paths.append(path)
        return saved

    async def url(self, path: str) -> str | None:
        return await self._store.url(path)

    async def delete_all(self, prefix: str) -> None:
        await self._store.delete_all(prefix)


async def voiced_reviews(engine: AsyncEngine, user_id: int) -> int:
    """デモの週次レビューのうち、声が付いた数。tts に断られても seed は通るので、数で確かめる。"""
    async with engine.connect() as conn:
        count = await conn.scalar(
            select(func.count())
            .select_from(WeeklyReview)
            .where(WeeklyReview.user_id == user_id, WeeklyReview.audio_path.is_not(None))
        )
    return count or 0


class _UploadOnly:
    """手元から seed を流すときの音声の置き場所。置く・消すだけで、署名はしない。

    手元の Google アカウントの資格情報では署名付き URL を作れない。seed は URL を使わない
    ので、署名のたびにエラーのログを出さないよう、署名しない。
    """

    def __init__(self, store: AudioStore) -> None:
        self._store = store

    async def put(self, path: str, data: bytes, content_type: str) -> bool:
        return await self._store.put(path, data, content_type)

    async def url(self, path: str) -> str | None:
        return None

    async def delete_all(self, prefix: str) -> None:
        await self._store.delete_all(prefix)


async def main() -> None:
    settings = get_settings()
    token = os.environ.get("TTS_ID_TOKEN")

    async def given_token() -> str:
        return token or ""

    voice = voices(kokoro_voice(settings, given_token if token else None), google_voice(settings))
    store = audio_store(settings)
    engine = get_engine()
    user_ids = await seed_demo_atomically(
        engine,
        gemini_writer(settings),
        jev_checker(settings),
        voice=voice,
        audio=None if store is None else _UploadOnly(store),
    )
    for language, user_id in zip(Language, user_ids, strict=True):
        print(f"demo user {user_id} ({language}): {FIRST_DAY} to {LAST_DAY}")
    if voice is None or store is None:
        print("no audio: set TTS_URL, GOOGLE_TTS_MODEL and AUDIO_BUCKET to voice the reviews")
        return
    missing = False
    for language, user_id in zip(Language, user_ids, strict=True):
        voiced = await voiced_reviews(engine, user_id)
        print(f"audio ({language}): {voiced} of {REVIEWS} reviews")
        missing = missing or voiced < REVIEWS
    if missing:
        # 声がない週は、ゲストには字幕だけで見える。声のログを見て、流し直す
        print("some reviews have no audio: check the voice warnings above and run again")


if __name__ == "__main__":
    asyncio.run(main())
