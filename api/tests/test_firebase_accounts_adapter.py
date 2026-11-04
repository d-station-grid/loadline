from collections.abc import Iterator
from typing import Any

import pytest
from firebase_admin import auth as firebase_auth
from firebase_admin import exceptions as firebase_exceptions
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters import firebase_accounts
from app.adapters.firebase_accounts import FirebaseAccountDeleter, account_deleter
from app.core.auth import get_token_verifier
from app.core.config import Settings
from app.main import app
from app.models import User
from app.routers.deps import get_account_deleter
from app.services.accounts import AccountDeleteError
from tests.factories import UserFactory
from tests.test_me_api import HEADERS, FakeVerifier


@pytest.fixture(autouse=True)
def no_adc(monkeypatch: pytest.MonkeyPatch) -> None:
    # ADC を読みに行くと DefaultCredentialsError になる環境。CI にも認証情報はない
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "/nonexistent")


class FakeDeleteUser:
    """firebase_auth.delete_user の代わり。error があれば上げる。"""

    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[str] = []
        self.error = error

    def __call__(self, uid: str, app: Any = None) -> None:
        self.calls.append(uid)
        assert app is not None and app.name == firebase_accounts.APP_NAME
        if self.error is not None:
            raise self.error


@pytest.fixture
def delete_user(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeDeleteUser]:
    fake = FakeDeleteUser()
    monkeypatch.setattr(firebase_auth, "delete_user", fake)
    yield fake


def test_building_does_not_read_credentials() -> None:
    # 起動や import のときは資格情報を読まない。読むのは消すとき
    deleter = account_deleter(Settings(firebase_project_id="loadline-app"))

    assert isinstance(deleter, FirebaseAccountDeleter)


async def test_delete_calls_firebase_with_the_admin_app(delete_user: FakeDeleteUser) -> None:
    await FirebaseAccountDeleter("loadline-app").delete("uid-1")

    assert delete_user.calls == ["uid-1"]


async def test_user_already_gone_counts_as_deleted(delete_user: FakeDeleteUser) -> None:
    delete_user.error = firebase_auth.UserNotFoundError("no user record")

    await FirebaseAccountDeleter("loadline-app").delete("uid-1")

    assert delete_user.calls == ["uid-1"]


async def test_firebase_error_is_account_delete_error(delete_user: FakeDeleteUser) -> None:
    delete_user.error = firebase_exceptions.UnavailableError("try later")

    with pytest.raises(AccountDeleteError):
        await FirebaseAccountDeleter("loadline-app").delete("uid-1")


async def test_missing_credentials_is_account_delete_error() -> None:
    # 本物の delete_user が資格情報を読みに行き、見つからない
    with pytest.raises(AccountDeleteError):
        await FirebaseAccountDeleter("loadline-app").delete("uid-1")


async def test_api_deletes_the_user_missing_from_firebase(
    client: AsyncClient, session: AsyncSession, delete_user: FakeDeleteUser
) -> None:
    delete_user.error = firebase_auth.UserNotFoundError("no user record")
    user = await UserFactory.create_async(firebase_uid="uid-1")
    await session.commit()
    user_id = user.id
    app.dependency_overrides[get_token_verifier] = FakeVerifier
    app.dependency_overrides[get_account_deleter] = lambda: FirebaseAccountDeleter("loadline-app")

    res = await client.delete("/me", headers=HEADERS)

    assert res.status_code == 204
    assert delete_user.calls == ["uid-1"]
    assert await session.scalar(select(func.count()).where(User.id == user_id)) == 0
