from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Identity, get_identity
from app.core.db import get_session
from app.models import User
from app.services.users import get_or_create_user


async def get_current_user(
    identity: Annotated[Identity, Depends(get_identity)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    """ログイン済みの本人の行。ID トークンの検証は get_identity に任せる。"""
    return await get_or_create_user(session, identity)


CurrentUser = Annotated[User, Depends(get_current_user)]
DbSession = Annotated[AsyncSession, Depends(get_session)]
