"""主な流れを、API だけを順に呼んで通す。

ログイン → 設定 → トークン発行 → 記録の受け取り → 一覧 → 1 件の詳細 → ダッシュボード
→ 振り返り → 選択肢の保存。前の段で入れたものが、次の段の応答に出ることを確かめる。
DB は本物の Postgres（テスト用の DB）を通る。
"""

from collections.abc import Iterator
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient

from app.core.auth import Identity, InvalidTokenError, get_token_verifier
from app.domain.review_week import review_period
from app.main import app

LOGIN = {"Authorization": "Bearer good"}
TOKYO = ZoneInfo("Asia/Tokyo")
REVIEW_WEEKDAY = 0  # 月曜
SETTINGS = {
    "max_heart_rate": 177,
    "resting_heart_rate": 75,
    "zone_boundary_1": 130,
    "zone_boundary_2": 155,
    "timezone": "Asia/Tokyo",
    "review_weekday": REVIEW_WEEKDAY,
    "send_notes_to_ai": True,
}


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


def _at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=TOKYO)


def _fmt(at: datetime) -> str:
    """Health Auto Export と同じ "2026-09-13 14:10:45 +0900" の形。"""
    return at.strftime("%Y-%m-%d %H:%M:%S %z")


def _workout(external_id: str, name: str, start: datetime, bpms: list[int]) -> dict[str, Any]:
    """1 分ごとの心拍を持つ Apple Watch のワークアウト。"""
    minutes = len(bpms)
    return {
        "id": external_id,
        "name": name,
        "start": _fmt(start),
        "end": _fmt(start + timedelta(minutes=minutes)),
        "duration": minutes * 60.0,
        "source": {"name": "Apple Watch"},
        "avgHeartRate": {"qty": sum(bpms) / minutes},
        "maxHeartRate": {"qty": max(bpms)},
        "heartRateData": [
            {"date": _fmt(start + timedelta(minutes=i)), "Min": b - 3, "Avg": b, "Max": b + 3}
            for i, b in enumerate(bpms)
        ],
    }


async def test_main_flow_from_token_to_selection(client: AsyncClient) -> None:
    # 振り返る週は、今日から決まる「今の振り返りの週」。記録はその週の中に置く
    start, end = review_period(datetime.now(TOKYO).date(), REVIEW_WEEKDAY)
    ride_day, run_day = start + timedelta(days=1), start + timedelta(days=3)

    # ログインと設定
    assert (await client.post("/auth/login", headers=LOGIN)).status_code == 200
    put = await client.put("/settings", json=SETTINGS, headers=LOGIN)
    assert put.status_code == 200

    # トークンを発行し、そのトークンで記録を送る
    issued = await client.post("/settings/ingest-token", headers=LOGIN)
    assert issued.status_code == 200
    token = issued.json()["token"]
    payload = {
        "data": {
            "workouts": [
                # 30 分ずつ。ライドは低・中・高に 10 分ずつ、ランは中だけ
                _workout(
                    "ride-1",
                    "屋外サイクリング",
                    _at(ride_day, 7),
                    [120] * 10 + [140] * 10 + [160] * 10,
                ),
                _workout("run-1", "Outdoor Run", _at(run_day, 18), [145] * 30),
            ],
            "metrics": [
                {
                    "name": "vo2_max",
                    "data": [
                        {"date": _fmt(_at(run_day, 19)), "qty": 48.26, "source": "Apple Watch"}
                    ],
                }
            ],
        }
    }
    ingested = await client.post(
        "/ingest", json=payload, headers={"Authorization": f"Bearer {token}"}
    )
    assert ingested.status_code == 200
    assert ingested.json()["workouts_added"] == 2
    assert ingested.json()["vo2max_added"] == 1
    assert (await client.get("/settings", headers=LOGIN)).json()["ingest_token_last_four"] == (
        issued.json()["last_four"]
    )

    # 一覧は新しい順
    listed = await client.get("/workouts", headers=LOGIN)
    assert listed.status_code == 200
    items = listed.json()["items"]
    assert [w["sport"] for w in items] == ["run", "ride"]
    assert [w["duration_sec"] for w in items] == [1800, 1800]

    # 1 件の詳細に、送った心拍と強度ごとの時間が出る
    detail = await client.get(f"/workouts/{items[1]['id']}", headers=LOGIN)
    assert detail.status_code == 200
    assert len(detail.json()["heart_rates"]) == 30
    assert detail.json()["zones"] == {"low": 600, "mid": 600, "high": 600}

    # ダッシュボードに、その週の負荷と VO2max が出る
    dashboard = await client.get(
        "/dashboard", params={"since": start.isoformat(), "until": end.isoformat()}, headers=LOGIN
    )
    assert dashboard.status_code == 200
    board = dashboard.json()
    assert board["needs_heart_rate_settings"] is False
    assert [w["day"] for w in board["workouts"]] == [ride_day.isoformat(), run_day.isoformat()]
    loads = {d["day"]: d["load"] for d in board["days"]}
    assert loads[ride_day.isoformat()] > 0
    assert loads[run_day.isoformat()] > 0
    assert loads[start.isoformat()] == 0
    assert board["zones"] == {"low": 600, "mid": 600 + 1800, "high": 600}
    assert [(p["day"], p["value"]) for p in board["vo2max"]] == [(run_day.isoformat(), 48.3)]

    # 振り返りを作る。記録を始めたばかりなので「記録が足りない」で、回数は送った 2 回
    created = await client.post("/reviews", headers=LOGIN)
    assert created.status_code == 201
    review = created.json()
    assert (review["period_start"], review["period_end"]) == (start.isoformat(), end.isoformat())
    assert review["situation"] == "not_enough_data"
    assert "This week you did 2 sessions." in review["script"]

    # 選択肢を選ぶと、今の週の振り返りにも選んだ印が残る
    option = review["options"][0]
    selected = await client.put(
        f"/reviews/{review['id']}/selection", json={"option_id": option["id"]}, headers=LOGIN
    )
    assert selected.status_code == 200
    current = await client.get("/reviews/current", headers=LOGIN)
    assert current.status_code == 200
    chosen = [o["id"] for o in current.json()["options"] if o["selected_at"] is not None]
    assert chosen == [option["id"]]
