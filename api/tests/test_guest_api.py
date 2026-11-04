"""ゲスト（Firebase の匿名ログイン）は、デモの利用者のデータを見るだけ。"""

import asyncio
from collections.abc import AsyncIterator, Iterator
from datetime import date
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

import scripts.seed_demo as seed_module
from app.core.auth import Identity, InvalidTokenError, get_token_verifier, identity_from_claims
from app.main import app
from app.models import (
    IngestToken,
    Note,
    User,
    Vo2maxReading,
    WeeklyReview,
    WeeklyReviewOption,
    Workout,
    WorkoutHeartRate,
)
from app.routers.deps import get_account_deleter
from app.services.reviews import select_option
from scripts.seed_demo import FIRST_DAY, LAST_DAY, REVIEWS, seed_demo, seed_demo_atomically
from tests.test_me_api import FakeDeleter

GUEST = {"Authorization": "Bearer guest"}
ANOTHER_GUEST = {"Authorization": "Bearer guest-2"}


class FakeVerifier:
    """guest と guest-2 は匿名ログインの別の人。"""

    def verify(self, token: str) -> Identity:
        if token in ("guest", "guest-2"):
            return Identity(uid=f"anon-{token}", email="", is_anonymous=True)
        raise InvalidTokenError


@pytest.fixture(autouse=True)
def fake_verifier() -> Iterator[FakeDeleter]:
    deleter = FakeDeleter()
    app.dependency_overrides[get_token_verifier] = FakeVerifier
    app.dependency_overrides[get_account_deleter] = lambda: deleter
    yield deleter
    app.dependency_overrides.pop(get_token_verifier, None)
    app.dependency_overrides.pop(get_account_deleter, None)


@pytest.fixture
async def demo(session: AsyncSession) -> User:
    return await seed_demo(session)


def test_anonymous_sign_in_is_read_from_the_claims() -> None:
    anonymous = identity_from_claims({"uid": "a", "firebase": {"sign_in_provider": "anonymous"}})
    google = identity_from_claims(
        {"uid": "g", "email": "g@example.com", "firebase": {"sign_in_provider": "google.com"}}
    )

    assert anonymous == Identity(uid="a", email="", is_anonymous=True)
    assert google == Identity(uid="g", email="g@example.com", is_anonymous=False)


async def test_guests_share_the_demo_user_without_new_rows(
    client: AsyncClient, session: AsyncSession, demo: User
) -> None:
    first = await client.post("/auth/login", headers=GUEST)
    second = await client.post("/auth/login", headers=ANOTHER_GUEST)

    assert first.status_code == 200
    assert first.json()["id"] == second.json()["id"] == demo.id
    assert await session.scalar(select(func.count()).select_from(User)) == 1


async def test_guest_login_is_503_before_the_demo_data_is_seeded(client: AsyncClient) -> None:
    res = await client.post("/auth/login", headers=GUEST)

    assert res.status_code == 503


async def test_guest_sees_the_last_weeks_of_the_demo_data(client: AsyncClient, demo: User) -> None:
    """デモデータは日付が動かない。直近 N 週は、最後のワークアウトの日で切る。"""
    dashboard = await client.get("/dashboard", params={"weeks": 4}, headers=GUEST)
    workouts = await client.get("/workouts", params={"weeks": 4}, headers=GUEST)

    assert dashboard.status_code == 200
    body = dashboard.json()
    assert body["until"] == LAST_DAY.isoformat()
    assert body["needs_heart_rate_settings"] is False
    assert body["workouts"]
    assert body["vo2max"]
    assert workouts.status_code == 200
    assert workouts.json()["items"]
    assert date.fromisoformat(workouts.json()["since"][:10]) == date(2026, 10, 4)


async def test_guest_sees_the_latest_seeded_review_with_options_not_chosen(
    client: AsyncClient, demo: User
) -> None:
    res = await client.get("/reviews/current", headers=GUEST)

    assert res.status_code == 200
    review = res.json()
    assert review["period_end"] == LAST_DAY.isoformat()
    assert review["script"]
    assert len(review["options"]) >= 2
    assert all(o["selected_at"] is None for o in review["options"])


async def test_guest_can_read_notes_and_settings(client: AsyncClient, demo: User) -> None:
    notes = await client.get("/notes", params={"since": FIRST_DAY.isoformat()}, headers=GUEST)
    settings = await client.get("/settings", headers=GUEST)

    assert notes.status_code == 200
    assert notes.json()["items"]
    assert settings.status_code == 200
    assert settings.json()["max_heart_rate"] == demo.max_heart_rate


async def _snapshot(session: AsyncSession) -> dict[str, object]:
    """デモデータの中身。書き込みを断ったあとに変わっていないことを比べる。"""
    counts = {
        model.__name__: await session.scalar(select(func.count()).select_from(model))
        for model in (
            User,
            Workout,
            WorkoutHeartRate,
            Vo2maxReading,
            Note,
            IngestToken,
            WeeklyReview,
            WeeklyReviewOption,
        )
    }
    notes = (await session.execute(select(Note.id, Note.body, Note.label).order_by(Note.id))).all()
    selected = (
        await session.execute(
            select(WeeklyReviewOption.id, WeeklyReviewOption.selected_at).order_by(
                WeeklyReviewOption.id
            )
        )
    ).all()
    user = (
        await session.execute(
            select(User.max_heart_rate, User.timezone, User.review_weekday, User.send_notes_to_ai)
        )
    ).all()
    return {"counts": counts, "notes": notes, "selected": selected, "user": user}


async def test_every_write_is_403_and_the_demo_data_does_not_change(
    client: AsyncClient, session: AsyncSession, demo: User, fake_verifier: FakeDeleter
) -> None:
    review = (await client.get("/reviews/current", headers=GUEST)).json()
    note = (
        await client.get("/notes", params={"since": FIRST_DAY.isoformat()}, headers=GUEST)
    ).json()["items"][0]
    before = await _snapshot(session)

    writes = [
        ("POST", "/notes", {"date": LAST_DAY.isoformat(), "body": "hi", "label": None}),
        ("PATCH", f"/notes/{note['id']}", {"body": "changed"}),
        ("DELETE", f"/notes/{note['id']}", None),
        (
            "PUT",
            "/settings",
            {
                "max_heart_rate": 200,
                "resting_heart_rate": 40,
                "zone_boundary_1": None,
                "zone_boundary_2": None,
                "timezone": "UTC",
                "review_weekday": 3,
                "send_notes_to_ai": False,
            },
        ),
        ("POST", "/settings/ingest-token", None),
        ("POST", "/reviews", None),
        ("PUT", f"/reviews/{review['id']}/selection", {"option_id": review["options"][0]["id"]}),
        ("DELETE", "/me", None),
    ]
    for method, path, body in writes:
        res = await client.request(method, path, json=body, headers=GUEST)
        assert res.status_code == 403, (method, path, res.text)

    assert await _snapshot(session) == before
    assert fake_verifier.deleted == []


async def test_seed_demo_can_run_again(session: AsyncSession, demo: User) -> None:
    """流し直すと作り直す。デモの利用者は 1 人のまま、振り返りも増えない。"""
    again = await seed_demo(session)

    users = await session.scalar(select(func.count()).select_from(User).where(User.is_demo))
    reviews = await session.scalar(
        select(func.count()).select_from(WeeklyReview).where(WeeklyReview.user_id == again.id)
    )
    assert users == 1
    assert reviews == REVIEWS


async def test_only_one_demo_user_can_exist(session: AsyncSession, demo: User) -> None:
    """ゲストは全員デモの利用者 1 人として扱う。2 人目は DB が断る。"""
    session.add(User(email="second@loadline.invalid", is_demo=True))

    with pytest.raises(IntegrityError):
        await session.flush()


# ここから下は、seed をテストの外のトランザクションに入れずに本当に確定させる。
# 終わったらデモの利用者を消し、ほかのテストに残さない


@pytest.fixture
async def committed(engine: AsyncEngine) -> AsyncIterator[AsyncEngine]:
    yield engine
    async with engine.begin() as conn:
        await conn.execute(delete(User).where(User.is_demo.is_(True)))


async def _demo_state(engine: AsyncEngine) -> tuple[list[int], int, int]:
    """確定したデモの利用者の id、振り返りの数、選んだ選択肢の数。"""
    async with engine.connect() as conn:
        ids = list(await conn.scalars(select(User.id).where(User.is_demo.is_(True))))
        reviews = await conn.scalar(
            select(func.count()).select_from(WeeklyReview).where(WeeklyReview.user_id.in_(ids))
        )
        selected = await conn.scalar(
            select(func.count())
            .select_from(WeeklyReviewOption)
            .join(WeeklyReview)
            .where(WeeklyReview.user_id.in_(ids), WeeklyReviewOption.selected_at.is_not(None))
        )
    return ids, reviews or 0, selected or 0


async def test_a_failed_seed_keeps_the_previous_demo_data(
    committed: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """振り返りの途中で落ちても、前のデモがそのまま残る。半端なデモは見せない。"""
    first = await seed_demo_atomically(committed)

    calls = 0
    real = select_option

    async def fail_on_second(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("boom")
        return await real(*args, **kwargs)

    monkeypatch.setattr(seed_module, "select_option", fail_on_second)
    with pytest.raises(RuntimeError):
        await seed_demo_atomically(committed)

    assert await _demo_state(committed) == ([first], REVIEWS, REVIEWS - 1)


async def test_seeding_twice_at_once_leaves_one_demo_user(committed: AsyncEngine) -> None:
    await asyncio.gather(seed_demo_atomically(committed), seed_demo_atomically(committed))

    ids, reviews, selected = await _demo_state(committed)
    assert len(ids) == 1
    assert (reviews, selected) == (REVIEWS, REVIEWS - 1)
