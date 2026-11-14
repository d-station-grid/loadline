from functools import lru_cache
from typing import Annotated, Any

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.audio_storage import audio_store
from app.adapters.cloud_tasks import review_queue
from app.adapters.firebase_accounts import account_deleter
from app.adapters.gemini import gemini_writer
from app.adapters.jev import jev_checker
from app.adapters.tts import kokoro_voice
from app.core.auth import Identity, get_identity
from app.core.config import get_settings
from app.core.db import get_session
from app.models import User
from app.services.accounts import AccountDeleter
from app.services.audio import AudioStore, Voice
from app.services.auto_reviews import ReviewQueue
from app.services.reviews import LineChecker, ReviewWriter
from app.services.users import AccountDeletedError, DemoUnavailableError, get_or_create_user


async def resolve_user(
    session: AsyncSession,
    identity: Identity,
    timezone: str | None = None,
    language: str | None = None,
) -> User:
    """本人の行。なければ作る。timezone と language は行を作るときだけ使う。

    アカウントを消した人のトークンは、期限の前でも 401 にする。ゲスト（匿名ログイン）は
    デモの利用者になる。デモの利用者がまだいなければ 503。
    """
    try:
        return await get_or_create_user(session, identity, timezone, language)
    except AccountDeletedError:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, headers={"WWW-Authenticate": "Bearer"}
        ) from None
    except DemoUnavailableError:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "guest mode is not available"
        ) from None


async def get_current_user(
    identity: Annotated[Identity, Depends(get_identity)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    """ログイン済みの本人の行。ID トークンの検証は get_identity に任せる。"""
    return await resolve_user(session, identity)


CurrentUser = Annotated[User, Depends(get_current_user)]
DbSession = Annotated[AsyncSession, Depends(get_session)]
CurrentIdentity = Annotated[Identity, Depends(get_identity)]


def get_writable_user(user: CurrentUser) -> User:
    """書き込める本人。ゲスト（デモの利用者）は見るだけなので 403 にし、デモデータを守る。"""
    if user.is_demo:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "guests can only view")
    return user


WritableUser = Annotated[User, Depends(get_writable_user)]

# 書き込みの窓口に付ける、ゲストの 403 の説明
GUEST_FORBIDDEN: dict[int | str, dict[str, Any]] = {
    status.HTTP_403_FORBIDDEN: {"description": "ゲスト（デモの利用者）は見るだけで、書き込めない"}
}


@lru_cache
def get_review_writer() -> ReviewWriter | None:
    """週次レビューを書く Gemini。プロセスで 1 つ。GEMINI_PROJECT が空なら None（定型だけ）。"""
    return gemini_writer(get_settings())


ReviewWriterDep = Annotated[ReviewWriter | None, Depends(get_review_writer)]


@lru_cache
def get_line_checker() -> LineChecker | None:
    """セリフを確かめる Jev。プロセスで 1 つ。TYPESAFE_API_KEY が空なら None（定型だけ）。"""
    return jev_checker(get_settings())


LineCheckerDep = Annotated[LineChecker | None, Depends(get_line_checker)]


@lru_cache
def get_voice() -> Voice | None:
    """セリフを読み上げる tts。プロセスで 1 つ。TTS_URL が空なら None（声にしない）。"""
    return kokoro_voice(get_settings())


VoiceDep = Annotated[Voice | None, Depends(get_voice)]


@lru_cache
def get_audio_store() -> AudioStore | None:
    """音声を置く Cloud Storage。プロセスで 1 つ。AUDIO_BUCKET が空なら None（声にしない）。"""
    return audio_store(get_settings())


AudioStoreDep = Annotated[AudioStore | None, Depends(get_audio_store)]


@lru_cache
def get_review_queue() -> ReviewQueue | None:
    """週次レビューのタスクを積む Cloud Tasks。プロセスで 1 つ。TASKS_QUEUE が空なら None。"""
    return review_queue(get_settings())


ReviewQueueDep = Annotated[ReviewQueue | None, Depends(get_review_queue)]


@lru_cache
def get_account_deleter() -> AccountDeleter:
    """Firebase の利用者を消す。プロセスで 1 つ。資格情報は初めて消すときに読む。"""
    return account_deleter(get_settings())


AccountDeleterDep = Annotated[AccountDeleter, Depends(get_account_deleter)]
