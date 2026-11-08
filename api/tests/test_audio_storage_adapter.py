from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest
from google.api_core.exceptions import Forbidden, ServiceUnavailable

from app.adapters.audio_storage import GcsAudioStore, audio_store
from app.core.config import Settings
from app.services.accounts import AccountDeleteError

TTL = timedelta(hours=1)


class FakeBlob:
    def __init__(self, bucket: "FakeBucket", name: str) -> None:
        self.bucket = bucket
        self.name = name

    def upload_from_string(self, data: bytes, content_type: str) -> None:
        if self.bucket.fail is not None:
            raise self.bucket.fail
        self.bucket.files[self.name] = (data, content_type)

    def generate_signed_url(self, **kwargs: Any) -> str:
        if self.bucket.fail is not None:
            raise self.bucket.fail
        self.bucket.signed.append((self.name, kwargs))
        return f"https://storage.example/{self.name}?signed"


class FakeBucket:
    """Cloud Storage のバケットの代わり。置いたファイルを名前で持つ。"""

    def __init__(self) -> None:
        self.files: dict[str, tuple[bytes, str]] = {}
        self.signed: list[tuple[str, dict[str, Any]]] = []
        self.fail: Exception | None = None

    def blob(self, name: str) -> FakeBlob:
        return FakeBlob(self, name)

    def list_blobs(self, prefix: str) -> list[FakeBlob]:
        if self.fail is not None:
            raise self.fail
        return [FakeBlob(self, n) for n in self.files if n.startswith(prefix)]

    def delete_blobs(self, blobs: list[FakeBlob], on_error: Callable[[FakeBlob], None]) -> None:
        for b in blobs:
            if self.files.pop(b.name, None) is None:
                on_error(b)


class FakeClient:
    def __init__(self, bucket: FakeBucket) -> None:
        self._bucket = bucket
        self.names: list[str] = []

    def bucket(self, name: str) -> FakeBucket:
        self.names.append(name)
        return self._bucket


class FakeCredentials:
    """Cloud Run の資格情報の代わり。取り直すまでメールは "default" のまま。"""

    def __init__(self) -> None:
        self.valid = False
        self.token: str | None = None
        self.service_account_email = "default"

    def refresh(self, request: Any) -> None:
        self.valid = True
        self.token = "access-token"
        self.service_account_email = "loadline-api@loadline-app.iam.gserviceaccount.com"


def _store(bucket: FakeBucket, credentials: Any = None) -> GcsAudioStore:
    return GcsAudioStore("audio", TTL, credentials=credentials, client=FakeClient(bucket))


async def test_put_saves_the_wav() -> None:
    bucket = FakeBucket()

    assert await _store(bucket).put("users/1/reviews/2.wav", b"RIFF")
    assert bucket.files == {"users/1/reviews/2.wav": (b"RIFF", "audio/wav")}


FORBIDDEN = Forbidden("no")  # type: ignore[no-untyped-call]
DOWN = ServiceUnavailable("down")  # type: ignore[no-untyped-call]


@pytest.mark.parametrize("error", [FORBIDDEN, DOWN], ids=["forbidden", "down"])
async def test_put_failure_is_false(error: Exception) -> None:
    bucket = FakeBucket()
    bucket.fail = error

    assert not await _store(bucket).put("users/1/reviews/2.wav", b"RIFF")


async def test_url_is_signed_with_iam_as_the_service_account() -> None:
    # Cloud Run には鍵がないので、メールと access token を渡して IAM に署名させる
    bucket = FakeBucket()

    url = await _store(bucket, FakeCredentials()).url("users/1/reviews/2.wav")

    assert url == "https://storage.example/users/1/reviews/2.wav?signed"
    ((name, kwargs),) = bucket.signed
    assert name == "users/1/reviews/2.wav"
    assert kwargs == {
        "version": "v4",
        "expiration": TTL,
        "method": "GET",
        "service_account_email": "loadline-api@loadline-app.iam.gserviceaccount.com",
        "access_token": "access-token",
    }


async def test_url_failure_is_none() -> None:
    bucket = FakeBucket()
    bucket.fail = FORBIDDEN

    assert await _store(bucket, FakeCredentials()).url("users/1/reviews/2.wav") is None


async def test_delete_all_removes_only_the_prefix() -> None:
    bucket = FakeBucket()
    for name in ["users/1/reviews/2.wav", "users/1/reviews/3.wav", "users/10/reviews/4.wav"]:
        bucket.files[name] = (b"RIFF", "audio/wav")

    await _store(bucket).delete_all("users/1/")

    # users/10/ は users/1 で始まるが、/ まで含めて比べるので残る
    assert list(bucket.files) == ["users/10/reviews/4.wav"]


async def test_delete_all_with_nothing_to_delete() -> None:
    await _store(FakeBucket()).delete_all("users/1/")


async def test_delete_failure_is_an_account_delete_error() -> None:
    bucket = FakeBucket()
    bucket.fail = DOWN

    with pytest.raises(AccountDeleteError):
        await _store(bucket).delete_all("users/1/")


async def test_already_deleted_file_is_not_an_error() -> None:
    bucket = FakeBucket()
    bucket.files["users/1/reviews/2.wav"] = (b"RIFF", "audio/wav")
    store = _store(bucket)
    # 一覧を取ったあとに、別の処理が消した
    original = bucket.list_blobs

    def listed_then_gone(prefix: str) -> list[FakeBlob]:
        blobs = original(prefix)
        bucket.files.clear()
        return blobs

    bucket.list_blobs = listed_then_gone  # type: ignore[method-assign]

    await store.delete_all("users/1/")


def test_no_store_without_the_bucket() -> None:
    assert audio_store(Settings(audio_bucket="")) is None


def test_store_does_not_read_credentials_until_used() -> None:
    # CI など資格情報のない環境でも、設定から作るだけなら落ちない
    assert audio_store(Settings(audio_bucket="loadline-app-audio")) is not None
