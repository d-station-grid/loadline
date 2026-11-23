from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.routers.deps import IngestLimiter, enforce_rate_limit
from app.schemas.ingest import IngestPayload, IngestResult
from app.services.ingest import ingest
from app.services.ingest_tokens import find_active_token, mark_token_used

router = APIRouter(prefix="/ingest", tags=["ingest"])

_bearer = HTTPBearer(auto_error=False)


async def get_ingest_user_id(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    session: Annotated[AsyncSession, Depends(get_session)],
    limiter: IngestLimiter,
) -> int:
    """Authorization: Bearer <取り込み用トークン> から持ち主を決める。ログインとは別の鍵。"""
    unauthorized = HTTPException(
        status.HTTP_401_UNAUTHORIZED, headers={"WWW-Authenticate": "Bearer"}
    )
    if credentials is None:
        raise unauthorized
    row = await find_active_token(session, credentials.credentials)
    if row is None:
        raise unauthorized
    user_id = row.user_id
    # 上限を超えたリクエストでは DB に書かない
    enforce_rate_limit(limiter, f"ingest:{user_id}")
    await mark_token_used(session, row)
    return user_id


@router.post("", response_model=IngestResult)
async def receive(
    payload: IngestPayload,
    user_id: Annotated[int, Depends(get_ingest_user_id)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> IngestResult:
    """Health Auto Export の送信先。workouts と metrics を同じ URL で受け、中身で見分ける。"""
    return await ingest(session, user_id, payload)
