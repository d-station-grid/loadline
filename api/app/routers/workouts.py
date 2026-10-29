from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.exceptions import RequestValidationError

from app.routers.deps import CurrentUser, DbSession
from app.schemas.workouts import WorkoutDetail, WorkoutList
from app.services.workouts import workout_detail, workout_list

router = APIRouter(prefix="/workouts", tags=["workouts"])


@router.get("", response_model=WorkoutList)
async def read_workouts(
    user: CurrentUser,
    session: DbSession,
    since: Annotated[datetime | None, Query()] = None,
    until: Annotated[datetime | None, Query()] = None,
    before_id: Annotated[int | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    weeks: Annotated[int | None, Query(ge=1, le=520)] = None,
) -> WorkoutList:
    """本人のワークアウトを新しい順に。since 以上、until 未満。

    weeks は「直近 N 週」。since は利用者のタイムゾーンの今日から N 週前の日の 0 時になる
    （ダッシュボードの weeks と同じ日）。since とは一緒に渡せない。

    続きを取るときは、前のページの最後の 1 件の started_at を until に、id を before_id に
    渡す。開始時刻が同じ記録がページの境目にあっても抜けない。before_id は until と一緒に使う。
    since は 1 ページ目の応答の since を渡す。weeks を渡し直すと、日付をまたいだときに
    始まりが 1 日進み、境目の日の記録が続きから抜けるため。
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
    if before_id is not None and until is None:
        raise RequestValidationError(
            [
                {
                    "type": "value_error",
                    "loc": ("query", "before_id"),
                    "msg": "before_id needs until",
                    "input": before_id,
                }
            ]
        )
    return await workout_list(session, user, since, until, before_id, limit, weeks)


@router.get("/{workout_id}", response_model=WorkoutDetail)
async def read_workout(workout_id: int, user: CurrentUser, session: DbSession) -> WorkoutDetail:
    """1 件の詳細。心拍の推移と、設定の境目がそろっていれば強度ごとの時間。"""
    detail = await workout_detail(session, user, workout_id)
    if detail is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return detail
