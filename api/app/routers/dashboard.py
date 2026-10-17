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
    weeks: Annotated[int | None, Query(ge=1, le=520)] = None,
) -> Dashboard:
    """本人の負荷と推移。since と until は利用者のタイムゾーンでの日付で、両端を含む。

    weeks は「直近 N 週」。since は until（省けば今日）の N 週前の日になる。since とは
    一緒に渡せない。期間の誤りは、入力の検査と同じ 422 の形（detail が loc と msg の配列）で返す。
    """
    if weeks is not None and since is not None:
        raise RequestValidationError(
            [
                {
                    "type": "value_error",
                    "loc": ("query", "weeks"),
                    "msg": "weeks and since cannot be used together",
                    "input": weeks,
                }
            ]
        )
    try:
        return await build_dashboard(session, user, since, until, sport, weeks)
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
