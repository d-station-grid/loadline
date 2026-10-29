import copy
import json
from pathlib import Path
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User, Workout, WorkoutHeartRate
from app.services.ingest_tokens import current_token, issue_token
from tests.factories import UserFactory

SAMPLE = Path(__file__).parent / "fixtures" / "sample_health-auto-export_workouts-v2.json"
# SAMPLE のうち、取り込まれる方（Apple Watch）の記録
APPLE_WATCH_ID = "EC706163-46F5-4250-916B-3909437C8064"


async def _user_with_token(session: AsyncSession) -> tuple[User, str]:
    user = await UserFactory.create_async()
    token, _ = await issue_token(session, user.id)
    return user, token


async def test_without_token_is_401(client: AsyncClient) -> None:
    res = await client.post("/ingest", json={"data": {"workouts": []}})

    assert res.status_code == 401
    assert res.headers["WWW-Authenticate"] == "Bearer"


async def test_wrong_token_is_401(client: AsyncClient, session: AsyncSession) -> None:
    await _user_with_token(session)

    res = await client.post(
        "/ingest",
        json={"data": {"workouts": []}},
        headers={"Authorization": "Bearer not-the-token"},
    )

    assert res.status_code == 401


async def test_valid_token_ingests_and_marks_last_used(
    client: AsyncClient, session: AsyncSession
) -> None:
    user, token = await _user_with_token(session)

    res = await client.post(
        "/ingest",
        json=json.loads(SAMPLE.read_text()),
        headers={"Authorization": f"Bearer {token}"},
    )

    assert res.status_code == 200
    assert res.json() == {
        "workouts_added": 1,
        "workouts_updated": 0,
        "workouts_skipped": 1,
        "vo2max_added": 0,
        "vo2max_updated": 0,
        "vo2max_skipped": 0,
    }
    row = await current_token(session, user.id)
    assert row is not None
    assert row.last_used_at is not None


async def test_malformed_body_is_422(client: AsyncClient, session: AsyncSession) -> None:
    _, token = await _user_with_token(session)

    res = await client.post(
        "/ingest", json={"workouts": []}, headers={"Authorization": f"Bearer {token}"}
    )

    assert res.status_code == 422


async def _stored(session: AsyncSession, user_id: int) -> tuple[Any, ...]:
    """その利用者のワークアウト 1 件の値と、1 分ごとの平均心拍。

    行ではなく列で読む。行で読むと、セッションに残った前の値が返ることがあるため。
    """
    row = (
        await session.execute(
            select(
                Workout.id, Workout.duration_sec, Workout.avg_heart_rate, Workout.max_heart_rate
            ).where(Workout.user_id == user_id)
        )
    ).one()
    bpms = await session.scalars(
        select(WorkoutHeartRate.avg_bpm)
        .where(WorkoutHeartRate.workout_id == row.id)
        .order_by(WorkoutHeartRate.recorded_at)
    )
    return row.duration_sec, row.avg_heart_rate, row.max_heart_rate, list(bpms)


async def test_each_token_writes_only_to_its_owner(
    client: AsyncClient, session: AsyncSession
) -> None:
    """同じファイルを 2 人が送っても、それぞれの行に入る。A が中身を変えて送り直すと、
    A の行と心拍は書き換わり、B の行と心拍は元のまま。
    """
    a, token_a = await _user_with_token(session)
    b, token_b = await _user_with_token(session)
    body = json.loads(SAMPLE.read_text())
    for token in (token_a, token_b):
        res = await client.post("/ingest", json=body, headers={"Authorization": f"Bearer {token}"})
        assert res.json()["workouts_added"] == 1
    b_before = await _stored(session, b.id)
    assert len(b_before[3]) == 72

    # Apple Watch の 1 件の時間と心拍を変える。心拍は 30 件に減らし、どれも 150 にする
    changed = copy.deepcopy(body)
    workout = next(w for w in changed["data"]["workouts"] if w["id"] == APPLE_WATCH_ID)
    workout["duration"] = 3000
    workout["avgHeartRate"] = {"qty": 150}
    workout["maxHeartRate"] = {"qty": 160}
    workout["heartRateData"] = [
        {**p, "Min": 145, "Avg": 150, "Max": 155} for p in workout["heartRateData"][:30]
    ]
    again = await client.post(
        "/ingest", json=changed, headers={"Authorization": f"Bearer {token_a}"}
    )

    assert again.json()["workouts_updated"] == 1
    owners = await session.scalars(select(Workout.user_id).order_by(Workout.user_id))
    assert list(owners) == [a.id, b.id]
    assert await _stored(session, a.id) == (3000, 150, 160, [150] * 30)
    assert await _stored(session, b.id) == b_before
