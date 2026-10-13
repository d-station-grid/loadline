from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Identity, get_identity
from app.core.db import get_session
from app.schemas.user import UserOut
from app.services.users import get_or_create_user

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=UserOut)
async def login(
    identity: Annotated[Identity, Depends(get_identity)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> UserOut:
    """ID トークンで本人を確かめ、初回なら利用者の行を作って返す。"""
    user = await get_or_create_user(session, identity)
    return UserOut.model_validate(user)
