from dataclasses import asdict
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.exceptions import RequestValidationError

from app.domain.load import zone_times
from app.routers.deps import CurrentUser, DbSession
from app.schemas.workouts import (
    HeartRateSample,
    WorkoutDetail,
    WorkoutList,
    WorkoutSummary,
    ZoneSeconds,
)
from app.services.workouts import get_workout, heart_rates, list_workouts

router = APIRouter(prefix="/workouts", tags=["workouts"])


@router.get("", response_model=WorkoutList)
async def read_workouts(
    user: CurrentUser,
    session: DbSession,
    since: Annotated[datetime | None, Query()] = None,
    until: Annotated[datetime | None, Query()] = None,
    before_id: Annotated[int | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> WorkoutList:
    """本人のワークアウトを新しい順に。since 以上、until 未満。

    続きを取るときは、前のページの最後の 1 件の started_at を until に、id を before_id に
    渡す。開始時刻が同じ記録がページの境目にあっても抜けない。before_id は until と一緒に使う。
    """
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
    rows = await list_workouts(
        session, user.id, since=since, until=until, before_id=before_id, limit=limit
    )
    return WorkoutList(items=[WorkoutSummary.model_validate(r) for r in rows])


@router.get("/{workout_id}", response_model=WorkoutDetail)
async def read_workout(workout_id: int, user: CurrentUser, session: DbSession) -> WorkoutDetail:
    """1 件の詳細。心拍の推移と、設定の境目がそろっていれば強度ごとの時間。"""
    row = await get_workout(session, user.id, workout_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    samples = await heart_rates(session, row.id)
    zones = zone_times(
        [s.avg_bpm for s in samples], row.duration_sec, user.zone_boundary_1, user.zone_boundary_2
    )
    return WorkoutDetail(
        **WorkoutSummary.model_validate(row).model_dump(),
        heart_rates=[HeartRateSample.model_validate(s) for s in samples],
        zones=None if zones is None else ZoneSeconds(**asdict(zones)),
    )
