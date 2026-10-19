from collections.abc import Iterator
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Identity, InvalidTokenError, get_token_verifier
from app.main import app
from app.models import Note, User
from tests.factories import NoteFactory, UserFactory

HEADERS = {"Authorization": "Bearer good"}


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


async def _me(timezone: str = "Asia/Tokyo") -> User:
    """ログインする本人（uid-1）。"""
    return await UserFactory.create_async(firebase_uid="uid-1", timezone=timezone)


def _today(timezone: str) -> date:
    return datetime.now(ZoneInfo(timezone)).date()


async def test_create_returns_the_note(client: AsyncClient) -> None:
    res = await client.post(
        "/notes", json={"date": "2026-09-13", "body": "  Slept badly.  "}, headers=HEADERS
    )

    assert res.status_code == 201
    body = res.json()
    assert body["date"] == "2026-09-13"
    assert body["body"] == "Slept badly."  # 前後の空白は落とす
    assert body["label"] is None


async def test_created_note_is_listed_on_the_next_request(client: AsyncClient) -> None:
    """書いたメモは保存されていて、開き直しても残っている。"""
    await client.post("/notes", json={"date": "2026-09-13", "body": "Rest day."}, headers=HEADERS)

    res = await client.get("/notes", headers=HEADERS)

    assert [n["body"] for n in res.json()["items"]] == ["Rest day."]


async def test_second_note_on_the_same_date_is_conflict(
    client: AsyncClient, session: AsyncSession
) -> None:
    me = await _me()
    await NoteFactory.create_async(user_id=me.id, date=date(2026, 9, 13), body="First.")

    res = await client.post(
        "/notes", json={"date": "2026-09-13", "body": "Second."}, headers=HEADERS
    )

    assert res.status_code == 409
    # 元のメモは書き換わらない
    bodies = await session.scalars(select(Note.body).where(Note.user_id == me.id))
    assert list(bodies) == ["First."]


async def test_same_date_is_fine_for_another_user(client: AsyncClient) -> None:
    """1 日 1 件は利用者ごと。他人が同じ日に書いていても書ける。"""
    other = await UserFactory.create_async()
    await NoteFactory.create_async(user_id=other.id, date=date(2026, 9, 13))

    res = await client.post("/notes", json={"date": "2026-09-13", "body": "Mine."}, headers=HEADERS)

    assert res.status_code == 201


async def test_today_in_the_users_timezone_is_accepted(client: AsyncClient) -> None:
    """UTC より 14 時間進んだところの今日は、UTC ではまだ明日のことがある。それでも書ける。"""
    zone = "Pacific/Kiritimati"
    await _me(timezone=zone)

    res = await client.post(
        "/notes", json={"date": _today(zone).isoformat(), "body": "Today."}, headers=HEADERS
    )

    assert res.status_code == 201


async def test_future_date_in_the_users_timezone_is_rejected(
    client: AsyncClient, session: AsyncSession
) -> None:
    """UTC より 11 時間遅れたところの明日は、UTC では今日のことがある。それでも弾く。"""
    zone = "Pacific/Pago_Pago"
    await _me(timezone=zone)
    tomorrow = _today(zone) + timedelta(days=1)

    res = await client.post(
        "/notes", json={"date": tomorrow.isoformat(), "body": "Too early."}, headers=HEADERS
    )

    assert res.status_code == 400
    assert res.json() == {"detail": "date is in the future"}
    assert await session.scalar(select(func.count()).select_from(Note)) == 0


@pytest.mark.parametrize("text", ["", "   ", "x" * 2001])
async def test_empty_or_too_long_body_is_rejected(client: AsyncClient, text: str) -> None:
    res = await client.post("/notes", json={"date": "2026-09-13", "body": text}, headers=HEADERS)

    assert res.status_code == 422
    # 検証エラーの形（detail は項目ごとの配列）。生成した型の HTTPValidationError と同じ
    assert res.json()["detail"][0]["loc"] == ["body", "body"]


async def test_body_of_2000_characters_is_accepted(client: AsyncClient) -> None:
    res = await client.post(
        "/notes", json={"date": "2026-09-13", "body": "x" * 2000}, headers=HEADERS
    )

    assert res.status_code == 201


async def test_list_returns_only_own_notes_newest_first(client: AsyncClient) -> None:
    me = await _me()
    other = await UserFactory.create_async()
    await NoteFactory.create_async(user_id=me.id, date=date(2026, 9, 13), body="Older.")
    await NoteFactory.create_async(user_id=me.id, date=date(2026, 9, 20), body="Newer.")
    await NoteFactory.create_async(user_id=other.id, date=date(2026, 9, 15), body="Not mine.")

    res = await client.get("/notes", headers=HEADERS)

    assert res.status_code == 200
    assert [n["body"] for n in res.json()["items"]] == ["Newer.", "Older."]


async def test_list_filters_by_period(client: AsyncClient) -> None:
    """since は含み、until は含まない。"""
    me = await _me()
    for day in (12, 13, 19, 20):
        await NoteFactory.create_async(user_id=me.id, date=date(2026, 9, day))

    res = await client.get(
        "/notes", params={"since": "2026-09-13", "until": "2026-09-20"}, headers=HEADERS
    )

    assert [n["date"] for n in res.json()["items"]] == ["2026-09-19", "2026-09-13"]


async def test_notes_require_login(client: AsyncClient) -> None:
    listed = await client.get("/notes")
    created = await client.post("/notes", json={"date": "2026-09-13", "body": "x"})
    edited = await client.patch("/notes/1", json={"body": "x"})
    deleted = await client.delete("/notes/1")

    assert listed.status_code == 401
    assert created.status_code == 401
    assert edited.status_code == 401
    assert deleted.status_code == 401


async def test_edit_changes_only_the_body(client: AsyncClient) -> None:
    me = await _me()
    note = await NoteFactory.create_async(user_id=me.id, date=date(2026, 9, 13), body="Before.")

    res = await client.patch(f"/notes/{note.id}", json={"body": "  After.  "}, headers=HEADERS)

    assert res.status_code == 200
    body = res.json()
    assert body["id"] == note.id
    assert body["date"] == "2026-09-13"
    assert body["body"] == "After."  # 前後の空白は落とす


async def test_edited_note_is_listed_on_the_next_request(client: AsyncClient) -> None:
    """直したメモは保存されていて、開き直しても直したまま。"""
    me = await _me()
    note = await NoteFactory.create_async(user_id=me.id, body="Before.")

    await client.patch(f"/notes/{note.id}", json={"body": "After."}, headers=HEADERS)
    res = await client.get("/notes", headers=HEADERS)

    assert [n["body"] for n in res.json()["items"]] == ["After."]


async def test_edit_moves_updated_at_forward(client: AsyncClient) -> None:
    me = await _me()
    old = datetime(2026, 9, 13, tzinfo=ZoneInfo("UTC"))
    note = await NoteFactory.create_async(user_id=me.id, created_at=old, updated_at=old)

    res = await client.patch(f"/notes/{note.id}", json={"body": "After."}, headers=HEADERS)

    assert datetime.fromisoformat(res.json()["updated_at"]) > old
    assert datetime.fromisoformat(res.json()["created_at"]) == old


@pytest.mark.parametrize("text", ["", "   ", "x" * 2001])
async def test_edit_with_empty_or_too_long_body_is_rejected(
    client: AsyncClient, session: AsyncSession, text: str
) -> None:
    me = await _me()
    note = await NoteFactory.create_async(user_id=me.id, body="Before.")

    res = await client.patch(f"/notes/{note.id}", json={"body": text}, headers=HEADERS)

    assert res.status_code == 422
    assert await session.scalar(select(Note.body).where(Note.id == note.id)) == "Before."


async def test_edit_of_another_users_note_is_not_found(
    client: AsyncClient, session: AsyncSession
) -> None:
    await _me()
    other = await UserFactory.create_async()
    note = await NoteFactory.create_async(user_id=other.id, body="Not mine.")

    res = await client.patch(f"/notes/{note.id}", json={"body": "Hacked."}, headers=HEADERS)

    assert res.status_code == 404
    assert await session.scalar(select(Note.body).where(Note.id == note.id)) == "Not mine."


async def test_edit_of_missing_note_is_not_found(client: AsyncClient) -> None:
    await _me()

    res = await client.patch("/notes/999999", json={"body": "x"}, headers=HEADERS)

    assert res.status_code == 404


async def test_delete_removes_the_note(client: AsyncClient) -> None:
    me = await _me()
    note = await NoteFactory.create_async(user_id=me.id)

    res = await client.delete(f"/notes/{note.id}", headers=HEADERS)
    listed = await client.get("/notes", headers=HEADERS)

    assert res.status_code == 204
    assert res.content == b""
    assert listed.json()["items"] == []


async def test_deleted_day_can_be_written_again(client: AsyncClient) -> None:
    """消した日は空くので、1 日 1 件でもまた書ける。"""
    me = await _me()
    note = await NoteFactory.create_async(user_id=me.id, date=date(2026, 9, 13))

    await client.delete(f"/notes/{note.id}", headers=HEADERS)
    res = await client.post(
        "/notes", json={"date": "2026-09-13", "body": "Again."}, headers=HEADERS
    )

    assert res.status_code == 201


async def test_delete_of_another_users_note_is_not_found(
    client: AsyncClient, session: AsyncSession
) -> None:
    await _me()
    other = await UserFactory.create_async()
    note = await NoteFactory.create_async(user_id=other.id)

    res = await client.delete(f"/notes/{note.id}", headers=HEADERS)

    assert res.status_code == 404
    assert await session.scalar(select(func.count()).select_from(Note)) == 1


async def test_delete_of_missing_note_is_not_found(client: AsyncClient) -> None:
    await _me()

    res = await client.delete("/notes/999999", headers=HEADERS)

    assert res.status_code == 404
