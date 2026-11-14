from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query
from fastapi.exceptions import RequestValidationError

from app.domain.period import InvalidPeriodError
from app.routers.deps import CurrentUser, DbSession
from app.schemas.dashboard import Dashboard
from app.services.dashboard import build_dashboard

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("", response_model=Dashboard)
async def read_dashboard(
    user: CurrentUser,
    session: DbSession,
    since: Annotated[date | None, Query()] = None,
    until: Annotated[date | None, Query()] = None,
    weeks: Annotated[int | None, Query(ge=1, le=520)] = None,
) -> Dashboard:
    """本人の負荷と推移。since と until は利用者のタイムゾーンでの日付で、両端を含む。
    種目で変わる部分は全種目・サイクリング・ランの 3 つを by_sport にまとめて返すので、
    種目では絞らない。

    weeks は「直近 N 週」。until（省けば今日）までのちょうど N × 7 日で、since は N 週前の
    翌日になる。since とは
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
        return await build_dashboard(session, user, since, until, weeks)
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
