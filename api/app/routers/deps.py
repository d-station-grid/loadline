from functools import lru_cache
from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.cloud_tasks import review_queue
from app.adapters.firebase_accounts import account_deleter
from app.adapters.gemini import gemini_writer
from app.adapters.jev import jev_checker
from app.core.auth import Identity, get_identity
from app.core.config import get_settings
from app.core.db import get_session
from app.models import User
from app.services.accounts import AccountDeleter
from app.services.auto_reviews import ReviewQueue
from app.services.reviews import LineChecker, ReviewWriter
from app.services.users import AccountDeletedError, get_or_create_user


async def get_current_user(
    identity: Annotated[Identity, Depends(get_identity)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    """ログイン済みの本人の行。ID トークンの検証は get_identity に任せる。

    アカウントを消した人のトークンは、期限の前でも 401 にする。
    """
    try:
        return await get_or_create_user(session, identity)
    except AccountDeletedError:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, headers={"WWW-Authenticate": "Bearer"}
        ) from None


CurrentUser = Annotated[User, Depends(get_current_user)]
DbSession = Annotated[AsyncSession, Depends(get_session)]


@lru_cache
def get_review_writer() -> ReviewWriter | None:
    """振り返りを書く Gemini。プロセスで 1 つ。GEMINI_PROJECT が空なら None（定型だけ）。"""
    return gemini_writer(get_settings())


ReviewWriterDep = Annotated[ReviewWriter | None, Depends(get_review_writer)]


@lru_cache
def get_line_checker() -> LineChecker | None:
    """セリフを確かめる Jev。プロセスで 1 つ。TYPESAFE_API_KEY が空なら None（定型だけ）。"""
    return jev_checker(get_settings())


LineCheckerDep = Annotated[LineChecker | None, Depends(get_line_checker)]


@lru_cache
def get_review_queue() -> ReviewQueue | None:
    """振り返りのタスクを積む Cloud Tasks。プロセスで 1 つ。TASKS_QUEUE が空なら None。"""
    return review_queue(get_settings())


ReviewQueueDep = Annotated[ReviewQueue | None, Depends(get_review_queue)]


@lru_cache
def get_account_deleter() -> AccountDeleter:
    """Firebase の利用者を消す。プロセスで 1 つ。資格情報は初めて消すときに読む。"""
    return account_deleter(get_settings())


AccountDeleterDep = Annotated[AccountDeleter, Depends(get_account_deleter)]
