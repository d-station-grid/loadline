from dataclasses import asdict
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

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
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> WorkoutList:
    """本人のワークアウトを新しい順に。since 以上、until 未満。"""
    rows = await list_workouts(session, user.id, since=since, until=until, limit=limit)
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
