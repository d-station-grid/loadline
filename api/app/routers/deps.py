from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.gemini import gemini_writer
from app.core.auth import Identity, get_identity
from app.core.config import get_settings
from app.core.db import get_session
from app.models import User
from app.services.reviews import ReviewWriter
from app.services.users import get_or_create_user


async def get_current_user(
    identity: Annotated[Identity, Depends(get_identity)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    """ログイン済みの本人の行。ID トークンの検証は get_identity に任せる。"""
    return await get_or_create_user(session, identity)


CurrentUser = Annotated[User, Depends(get_current_user)]
DbSession = Annotated[AsyncSession, Depends(get_session)]


@lru_cache
def get_review_writer() -> ReviewWriter | None:
    """振り返りを書く Gemini。プロセスで 1 つ。GEMINI_PROJECT が空なら None（定型だけ）。"""
    return gemini_writer(get_settings())


ReviewWriterDep = Annotated[ReviewWriter | None, Depends(get_review_writer)]
