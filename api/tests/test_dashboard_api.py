import json
from collections.abc import Iterator
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Identity, InvalidTokenError, get_token_verifier
from app.main import app
from app.models import User, Workout
from app.schemas.ingest import IngestPayload
from app.services.ingest import ingest
from tests.factories import (
    IngestTokenFactory,
    UserFactory,
    Vo2maxReadingFactory,
    WorkoutFactory,
)

HEADERS = {"Authorization": "Bearer good"}
# 2026-09-13 14:10 (JST) に始まる Apple Watch のサイクリング 1 件（4028 秒、心拍 72 サンプル）
SAMPLE = Path(__file__).parent / "fixtures" / "sample_health-auto-export_workouts-v2.json"
SAMPLE_DAY = "2026-09-13"
JST = ZoneInfo("Asia/Tokyo")


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


async def _user(
    session: AsyncSession, uid: str = "uid-1", *, settings: bool = True, **fields: Any
) -> User:
    """fixtures の実データ（心拍あり）を取り込んだ利用者。settings で心拍の最大と安静時を入れる。"""
    if settings:
        fields = {"max_heart_rate": 177, "resting_heart_rate": 75, **fields}
    user = await UserFactory.create_async(firebase_uid=uid, **fields)
    await ingest(session, user.id, IngestPayload.model_validate(json.loads(SAMPLE.read_text())))
    return user


async def _run(user: User, start: str) -> Workout:
    """心拍のない Apple Watch のラン 1 件。start は日本時間。"""
    started_at = datetime.fromisoformat(start).replace(tzinfo=JST)
    return await WorkoutFactory.create_async(user_id=user.id, sport="run", started_at=started_at)


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
    await _run(user, "2026-09-14 08:00:00")

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
    await _user(session, zone_boundary_1=130, zone_boundary_2=155)

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
    user = await _user(session, zone_boundary_1=130, zone_boundary_2=155)
    await _run(user, f"{SAMPLE_DAY} 06:00:00")

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
    for day, value in [("2026-09-01", "44.0"), ("2026-09-20", "46.0")]:
        await Vo2maxReadingFactory.create_async(
            user_id=user.id,
            measured_at=datetime.fromisoformat(f"{day} 08:00").replace(tzinfo=JST),
            value=Decimal(value),
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


async def test_weeks_starts_n_weeks_before_today_in_user_timezone(
    client: AsyncClient, session: AsyncSession
) -> None:
    """端末ではなく設定のタイムゾーンの今日から数える。UTC+14 なら、ほかの国より先に日付が進む。"""
    await _user(session, timezone="Pacific/Kiritimati")

    body = await _get(client, weeks="1")

    today = datetime.now(ZoneInfo("Pacific/Kiritimati")).date()
    assert body["until"] == today.isoformat()
    assert body["since"] == (today - timedelta(days=6)).isoformat()
    assert body["days"][0]["day"] == body["since"]


async def test_weeks_counts_back_from_until(client: AsyncClient, session: AsyncSession) -> None:
    await _user(session)

    body = await _get(client, weeks="12", until="2026-10-17")

    assert body["since"] == "2026-07-26"
    assert len(body["days"]) == 12 * 7


async def test_only_own_records(client: AsyncClient, session: AsyncSession) -> None:
    await _user(session, uid="uid-other")
    await UserFactory.create_async(firebase_uid="uid-1", max_heart_rate=177, resting_heart_rate=75)

    body = await _get(client, since=SAMPLE_DAY, until=SAMPLE_DAY)

    assert body["workouts"] == []
    assert body["days"][0]["load"] == 0


async def test_does_not_show_someone_elses_vo2max(
    client: AsyncClient, session: AsyncSession
) -> None:
    other = await _user(session, uid="uid-other")
    await Vo2maxReadingFactory.create_async(
        user_id=other.id,
        measured_at=datetime.fromisoformat(f"{SAMPLE_DAY} 08:00").replace(tzinfo=JST),
    )
    await UserFactory.create_async(firebase_uid="uid-1", max_heart_rate=177, resting_heart_rate=75)

    body = await _get(client, since=SAMPLE_DAY, until=SAMPLE_DAY)

    assert body["vo2max"] == []


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


@pytest.mark.parametrize(
    "params",
    [
        {"weeks": "12", "since": "2026-09-13"},
        {"weeks": "0"},
        {"weeks": "521"},
    ],
)
async def test_invalid_weeks_is_rejected(
    client: AsyncClient, session: AsyncSession, params: dict[str, str]
) -> None:
    await _user(session)

    res = await client.get("/dashboard", params=params, headers=HEADERS)

    assert res.status_code == 422
    (error,) = res.json()["detail"]
    assert error["loc"] == ["query", "weeks"]


async def test_requires_login(client: AsyncClient) -> None:
    res = await client.get("/dashboard")

    assert res.status_code == 401


async def _vo2max(user: User, day: str, value: str) -> None:
    measured_at = datetime.fromisoformat(f"{day} 07:00:00").replace(tzinfo=JST)
    await Vo2maxReadingFactory.create_async(
        user_id=user.id, measured_at=measured_at, value=Decimal(value)
    )


async def test_changes_compare_with_seven_days_before(
    client: AsyncClient, session: AsyncSession
) -> None:
    await _user(session)

    body = await _get(client, since=SAMPLE_DAY, until="2026-09-20")

    week_ago, now = body["days"][0], body["days"][-1]
    changes = body["changes"]
    assert changes["fitness"] == pytest.approx(now["fitness"] - week_ago["fitness"])
    assert changes["fatigue"] == pytest.approx(now["fatigue"] - week_ago["fatigue"])
    assert changes["headroom"] == pytest.approx(now["headroom"] - week_ago["headroom"])
    # 最初のワークアウトから 42 日に満たないので、余力の区分は出さない
    assert body["form"] == "not_enough_data"


async def test_changes_and_form_are_none_without_heart_rate_settings(
    client: AsyncClient, session: AsyncSession
) -> None:
    await _user(session, settings=False)

    body = await _get(client, since=SAMPLE_DAY, until="2026-09-20")

    assert body["changes"]["fitness"] is None
    assert body["changes"]["fatigue"] is None
    assert body["changes"]["headroom"] is None
    assert body["form"] is None


async def test_form_is_judged_after_enough_history(
    client: AsyncClient, session: AsyncSession
) -> None:
    """9/13 の 1 回だけで 42 日を過ぎると、疲労が抜けて休めている側になる。"""
    await _user(session)

    body = await _get(client, since="2026-10-25", until="2026-10-25")

    assert body["form"] == "fresh"


async def test_vo2max_change_compares_with_four_weeks_before(
    client: AsyncClient, session: AsyncSession
) -> None:
    user = await _user(session)
    await _vo2max(user, "2026-08-20", "45.0")
    # 9/20 の 28 日前（8/23）より後なので、比べる相手にしない
    await _vo2max(user, "2026-08-24", "40.0")
    await _vo2max(user, "2026-09-20", "47.5")

    body = await _get(client, since="2026-09-14", until="2026-09-20")
    without_old = await _get(client, since="2026-08-24", until="2026-08-24")

    assert body["changes"]["vo2max"] == pytest.approx(2.5)
    # 8/24 の 28 日前（7/27）より前に測定がない
    assert without_old["changes"]["vo2max"] is None


async def test_vo2max_change_is_none_without_a_reading_in_the_period(
    client: AsyncClient, session: AsyncSession
) -> None:
    user = await _user(session)
    await _vo2max(user, "2026-08-20", "45.0")

    body = await _get(client, since="2026-09-14", until="2026-09-20")

    assert body["vo2max"] == []
    assert body["changes"]["vo2max"] is None


async def test_totals_and_previous_totals_follow_the_sport(
    client: AsyncClient, session: AsyncSession
) -> None:
    user = await _user(session)
    # 期間（9/14〜9/20）に心拍のないラン 1 回。前の期間（9/7〜9/13）に心拍のあるサイクリング 1 回
    await _run(user, "2026-09-15 07:00:00")

    everything = await _get(client, since="2026-09-14", until="2026-09-20")
    rides = await _get(client, since="2026-09-14", until="2026-09-20", sport="ride")

    totals, previous = everything["totals"], everything["previous_totals"]
    assert (totals["start"], totals["end"]) == ("2026-09-14", "2026-09-20")
    assert (previous["start"], previous["end"]) == ("2026-09-07", SAMPLE_DAY)
    assert totals["workouts"] == 1
    assert totals["total_sec"] == 1800
    assert totals["load"] is None
    assert totals["load_per_workout"] is None
    assert totals["workouts_without_load"] == 1
    assert previous["workouts"] == 1
    assert previous["total_sec"] == 4028
    ride_load = (await _get(client, since=SAMPLE_DAY, until=SAMPLE_DAY))["workouts"][0]["load"]
    assert previous["load"] == pytest.approx(ride_load)
    assert previous["load_per_workout"] == pytest.approx(ride_load)
    # サイクリングだけなら、期間は 0 回で負荷も 0
    assert rides["totals"]["workouts"] == 0
    assert rides["totals"]["load"] == 0
    assert rides["previous_totals"]["workouts"] == 1


async def test_previous_totals_reach_beyond_the_warmup(
    client: AsyncClient, session: AsyncSession
) -> None:
    """期間が長いと、前の期間はウォームアップ（252 日）より前まで届く。そこも読む。"""
    user = await _user(session)
    # 期間は 273 日。前の期間は 2025-05-04〜2026-01-31、ウォームアップは 2025-05-25 から
    await _run(user, "2025-05-10 07:00:00")

    body = await _get(client, since="2026-02-01", until="2026-10-31")

    assert body["previous_totals"]["start"] == "2025-05-04"
    assert body["previous_totals"]["workouts"] == 1


async def test_zone_weeks_count_back_from_until(client: AsyncClient, session: AsyncSession) -> None:
    await _user(session, zone_boundary_1=130, zone_boundary_2=155)

    body = await _get(client, weeks="2", until="2026-09-19")

    weeks = body["zone_weeks"]
    assert [(w["start"], w["end"]) for w in weeks] == [
        ("2026-09-06", "2026-09-12"),
        (SAMPLE_DAY, "2026-09-19"),
    ]
    assert weeks[0]["zones"] == {"low": 0, "mid": 0, "high": 0}
    assert weeks[1]["zones"] == body["zones"]
    assert weeks[1]["workouts_without_zones"] == 0


async def test_zone_weeks_are_none_without_boundaries(
    client: AsyncClient, session: AsyncSession
) -> None:
    await _user(session)

    body = await _get(client, weeks="2", until="2026-09-19")

    assert body["zone_weeks"] is None


async def test_last_received_at_is_the_latest_use_of_any_token(
    client: AsyncClient, session: AsyncSession
) -> None:
    user = await _user(session)
    other = await UserFactory.create_async(firebase_uid="uid-other")
    latest = datetime(2026, 9, 24, 7, 12, tzinfo=JST)
    # 再発行で無効にした古いトークンが、いちばん最近に使われていることもある
    await IngestTokenFactory.create_async(
        user_id=user.id, last_used_at=latest, revoked_at=latest + timedelta(hours=1)
    )
    await IngestTokenFactory.create_async(user_id=user.id, last_used_at=latest - timedelta(days=1))
    await IngestTokenFactory.create_async(user_id=other.id, last_used_at=latest + timedelta(days=1))

    body = await _get(client, since=SAMPLE_DAY, until=SAMPLE_DAY)

    assert datetime.fromisoformat(body["last_received_at"]) == latest


async def test_last_received_at_is_none_before_anything_arrives(
    client: AsyncClient, session: AsyncSession
) -> None:
    await _user(session)

    body = await _get(client, since=SAMPLE_DAY, until=SAMPLE_DAY)

    assert body["last_received_at"] is None
