import json
from collections.abc import Iterator
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Identity, InvalidTokenError, get_token_verifier
from app.main import app
from app.models import User
from app.schemas.ingest import IngestPayload
from app.services.ingest import ingest

HEADERS = {"Authorization": "Bearer good"}
# 2026-09-13 14:10 (JST) に始まる Apple Watch のサイクリング 1 件（4028 秒、心拍 72 サンプル）
SAMPLE = Path(__file__).parent / "fixtures" / "sample_health-auto-export_workouts-v2.json"
SAMPLE_DAY = "2026-09-13"


class FakeVerifier:
    def verify(self, token: str) -> Identity:
        if token == "good":
            return Identity(uid="uid-1", email="one@example.com")
        raise InvalidTokenError


@pytest.fixture(autouse=True)
def fake_verifier() -> Iterator[None]:
    app.dependency_overrides[get_token_verifier] = FakeVerifier
    yield
    app.dependency_overrides.pop(get_token_verifier, None)


async def _user(session: AsyncSession, uid: str = "uid-1", *, settings: bool = True) -> User:
    user = User(firebase_uid=uid, email=f"{uid}@example.com")
    if settings:
        user.max_heart_rate = 177
        user.resting_heart_rate = 75
    session.add(user)
    await session.flush()
    await ingest(session, user.id, IngestPayload.model_validate(json.loads(SAMPLE.read_text())))
    return user


def _run(start: str, minutes: int = 30) -> IngestPayload:
    """心拍のない Apple Watch のラン 1 件。"""
    return IngestPayload.model_validate(
        {
            "data": {
                "workouts": [
                    {
                        "id": f"run-{start}",
                        "name": "屋外 ラン",
                        "start": f"{start} +0900",
                        "end": f"{start} +0900",
                        "duration": minutes * 60,
                        "source": {"name": "Apple\xa0Watch"},
                    }
                ]
            }
        }
    )


def _vo2max(*points: tuple[str, float]) -> IngestPayload:
    data = [{"date": f"{d} +0900", "qty": q, "source": "Apple\xa0Watch"} for d, q in points]
    return IngestPayload.model_validate(
        {"data": {"metrics": [{"name": "vo2_max", "units": "ml/(kg·min)", "data": data}]}}
    )


async def _get(client: AsyncClient, **params: str) -> dict[str, Any]:
    res = await client.get("/dashboard", params=params, headers=HEADERS)
    assert res.status_code == 200
    body: dict[str, Any] = res.json()
    return body


async def test_days_cover_the_period_and_carry_the_load(
    client: AsyncClient, session: AsyncSession
) -> None:
    await _user(session)

    body = await _get(client, since="2026-09-12", until="2026-09-14")

    assert [d["day"] for d in body["days"]] == ["2026-09-12", "2026-09-13", "2026-09-14"]
    loads = [d["load"] for d in body["days"]]
    assert loads[0] == 0
    assert loads[1] == pytest.approx(body["workouts"][0]["load"])
    assert loads[2] == 0
    # 負荷のあった日から体力と疲労が上がり、余力は体力から疲労を引いた値
    day = body["days"][1]
    assert day["fitness"] > 0
    assert day["fatigue"] > day["fitness"]
    assert day["headroom"] == pytest.approx(day["fitness"] - day["fatigue"])
    assert body["needs_heart_rate_settings"] is False


async def test_load_before_the_period_counts_toward_fitness(
    client: AsyncClient, session: AsyncSession
) -> None:
    """表示の期間より前の記録も、体力と疲労の初期値に入る。"""
    await _user(session)

    body = await _get(client, since="2026-10-01", until="2026-10-01")

    assert body["workouts"] == []
    assert body["days"][0]["load"] == 0
    assert body["days"][0]["fitness"] > 0


async def test_workout_point_has_load_and_day_in_user_timezone(
    client: AsyncClient, session: AsyncSession
) -> None:
    user = await _user(session)
    # 日本時間の 9/14 8:00 は UTC では 9/13 23:00。日付は利用者のタイムゾーンで区切る
    await ingest(session, user.id, _run("2026-09-14 08:00:00"))

    body = await _get(client, since=SAMPLE_DAY, until="2026-09-14")

    ride, run = body["workouts"]
    assert ride["day"] == SAMPLE_DAY
    assert ride["sport"] == "ride"
    assert ride["load"] > 0
    assert run["day"] == "2026-09-14"
    # 心拍がないので負荷は分からない。その日の負荷も None で、体力の計算は続く
    assert run["load"] is None
    assert body["days"][1]["load"] is None
    assert body["days"][1]["fitness"] > 0


async def test_sport_narrows_points_and_zones_but_not_days(
    client: AsyncClient, session: AsyncSession
) -> None:
    user = await _user(session)
    user.zone_boundary_1 = 130
    user.zone_boundary_2 = 155
    await session.commit()

    everything = await _get(client, since=SAMPLE_DAY, until=SAMPLE_DAY)
    runs = await _get(client, since=SAMPLE_DAY, until=SAMPLE_DAY, sport="run")

    assert len(everything["workouts"]) == 1
    zones = everything["zones"]
    assert zones["low"] + zones["mid"] + zones["high"] == 4028
    assert everything["workouts"][0]["high_sec"] == zones["high"]
    # ランだけに絞ると点と強度の時間は空になるが、体力と疲労はサイクリングも含めて出す
    assert runs["workouts"] == []
    assert runs["zones"] == {"low": 0, "mid": 0, "high": 0}
    assert runs["days"] == everything["days"]


async def test_zones_are_none_without_boundaries(
    client: AsyncClient, session: AsyncSession
) -> None:
    await _user(session)

    body = await _get(client, since=SAMPLE_DAY, until=SAMPLE_DAY)

    assert body["zones"] is None
    assert body["workouts"][0]["high_sec"] is None


async def test_zones_are_none_when_a_workout_has_no_heart_rate(
    client: AsyncClient, session: AsyncSession
) -> None:
    """心拍のない 1 件を外して足すと 0 秒に見えるので、合計ごと分からない（None）にする。"""
    user = await _user(session)
    user.zone_boundary_1 = 130
    user.zone_boundary_2 = 155
    await ingest(session, user.id, _run(f"{SAMPLE_DAY} 06:00:00"))

    everything = await _get(client, since=SAMPLE_DAY, until=SAMPLE_DAY)
    runs = await _get(client, since=SAMPLE_DAY, until=SAMPLE_DAY, sport="run")
    rides = await _get(client, since=SAMPLE_DAY, until=SAMPLE_DAY, sport="ride")

    assert everything["zones"] is None
    assert runs["zones"] is None
    assert runs["workouts"][0]["high_sec"] is None
    # 心拍のそろったサイクリングだけに絞れば、合計は出る
    assert sum(rides["zones"].values()) == 4028


async def test_without_heart_rate_settings_days_are_empty(
    client: AsyncClient, session: AsyncSession
) -> None:
    await _user(session, settings=False)

    body = await _get(client, since=SAMPLE_DAY, until=SAMPLE_DAY)

    assert body["needs_heart_rate_settings"] is True
    assert body["days"] == []
    assert body["workouts"][0]["load"] is None


async def test_vo2max_average_uses_readings_before_the_period(
    client: AsyncClient, session: AsyncSession
) -> None:
    user = await _user(session)
    await ingest(
        session,
        user.id,
        _vo2max(("2026-09-01 08:00:00", 44.0), ("2026-09-20 08:00:00", 46.0)),
    )

    body = await _get(client, since="2026-09-10", until="2026-09-30")

    # 9/1 は期間の外なので点にはならないが、9/20 の 30 日平均には入る
    assert body["vo2max"] == [{"day": "2026-09-20", "value": 46.0, "average": 45.0}]


async def test_without_since_starts_from_the_first_workout(
    client: AsyncClient, session: AsyncSession
) -> None:
    await _user(session)

    body = await _get(client, until="2026-09-20")

    assert body["since"] == SAMPLE_DAY
    assert len(body["days"]) == 8


async def test_without_until_ends_today(client: AsyncClient, session: AsyncSession) -> None:
    await _user(session)

    body = await _get(client, since="2026-10-01")

    assert date.fromisoformat(body["until"]) >= date(2026, 10, 16)
    assert body["days"][-1]["day"] == body["until"]


async def test_future_until_is_capped_at_today(client: AsyncClient, session: AsyncSession) -> None:
    """未来の日を負荷 0 で埋めて、体力と疲労が先まで減る線にしない。"""
    await _user(session)

    body = await _get(client, since="2026-10-01", until="9999-12-31")

    today = datetime.now(ZoneInfo("Asia/Tokyo")).date().isoformat()
    assert body["until"] == today
    assert body["days"][-1]["day"] == today


async def test_only_own_records(client: AsyncClient, session: AsyncSession) -> None:
    await _user(session, uid="uid-other")
    me = User(
        firebase_uid="uid-1", email="one@example.com", max_heart_rate=177, resting_heart_rate=75
    )
    session.add(me)
    await session.commit()

    body = await _get(client, since=SAMPLE_DAY, until=SAMPLE_DAY)

    assert body["workouts"] == []
    assert body["days"][0]["load"] == 0


@pytest.mark.parametrize(
    "params",
    [
        {"since": "2026-09-14", "until": "2026-09-13"},
        # until は今日で切る。未来の since は、切った後の検査で逆転として落ちる
        {"since": "2100-01-01"},
        {"since": "2100-01-01", "until": "2100-01-02"},
        # 足し引きで date の範囲からあふれる日付は、計算の前に落とす
        {"since": "0001-01-01", "until": "2026-09-13"},
    ],
)
async def test_invalid_period_is_rejected(
    client: AsyncClient, session: AsyncSession, params: dict[str, str]
) -> None:
    await _user(session)

    res = await client.get("/dashboard", params=params, headers=HEADERS)

    assert res.status_code == 422
    # 入力の検査と同じ形（OpenAPI の HTTPValidationError）で返す
    (error,) = res.json()["detail"]
    assert error["loc"] == ["query", "since"]
    assert error["type"] == "value_error"


async def test_requires_login(client: AsyncClient) -> None:
    res = await client.get("/dashboard")

    assert res.status_code == 401
