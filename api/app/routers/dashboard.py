from datetime import date
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from app.routers.deps import CurrentUser, DbSession
from app.schemas.dashboard import Dashboard, Sport
from app.services.dashboard import build_dashboard

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("", response_model=Dashboard)
async def read_dashboard(
    user: CurrentUser,
    session: DbSession,
    since: Annotated[date | None, Query()] = None,
    until: Annotated[date | None, Query()] = None,
    sport: Annotated[Sport, Query()] = "all",
) -> Dashboard:
    """本人の負荷と推移。since と until は利用者のタイムゾーンでの日付で、両端を含む。"""
    if since is not None and until is not None and since > until:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "since must not be after until")
    return await build_dashboard(session, user, since, until, sport)
