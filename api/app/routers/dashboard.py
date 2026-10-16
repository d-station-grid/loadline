from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query
from fastapi.exceptions import RequestValidationError

from app.routers.deps import CurrentUser, DbSession
from app.schemas.dashboard import Dashboard, Sport
from app.services.dashboard import InvalidPeriodError, build_dashboard

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("", response_model=Dashboard)
async def read_dashboard(
    user: CurrentUser,
    session: DbSession,
    since: Annotated[date | None, Query()] = None,
    until: Annotated[date | None, Query()] = None,
    sport: Annotated[Sport, Query()] = "all",
) -> Dashboard:
    """本人の負荷と推移。since と until は利用者のタイムゾーンでの日付で、両端を含む。

    期間の誤りは、入力の検査と同じ 422 の形（detail が loc と msg の配列）で返す。
    """
    try:
        return await build_dashboard(session, user, since, until, sport)
    except InvalidPeriodError as e:
        raise RequestValidationError(
            [
                {
                    "type": "value_error",
                    "loc": ("query", e.field),
                    "msg": str(e),
                    "input": e.value.isoformat(),
                }
            ]
        ) from e
