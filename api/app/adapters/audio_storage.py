"""振り返りの音声を Cloud Storage に置く、署名付き URL を出す、消す。

バケットは非公開。web には期限つきの署名付き URL を渡し、ブラウザはそれで直接読む。
Cloud Run には鍵のファイルがないので、署名は IAM の signBlob に頼む。本番は Cloud Run の
サービスアカウント（loadline-api）で、バケットの objectUser と、自身の
serviceAccountTokenCreator が要る。

SDK は同期なので、別のスレッドで待つ。資格情報を読むのは初めて使うときなので、CI など
資格情報のない環境でも起動や import では落ちない。
"""

import asyncio
import logging
import threading
from datetime import timedelta
from typing import Any

import google.auth
from google.api_core.exceptions import GoogleAPIError
from google.auth.credentials import Credentials
from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import Request
from google.cloud import storage  # type: ignore[attr-defined]

from app.core.config import Settings
from app.services.accounts import AccountDeleteError

logger = logging.getLogger(__name__)

_SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]


class GcsAudioStore:
    def __init__(
        self,
        bucket: str,
        url_ttl: timedelta,
        credentials: Credentials | None = None,
        client: Any = None,
    ) -> None:
        """credentials と client は、テストで差し替える。"""
        self._bucket_name = bucket
        self._url_ttl = url_ttl
        self._credentials = credentials
        self._client = client
        self._lock = threading.Lock()

    def _bucket(self) -> Any:
        with self._lock:
            if self._client is None:
                project = None
                if self._credentials is None:
                    self._credentials, project = google.auth.default(scopes=_SCOPES)
                self._client = storage.Client(project=project, credentials=self._credentials)
            return self._client.bucket(self._bucket_name)

    def _signer(self) -> dict[str, str]:
        """IAM で署名するための、サービスアカウントのメールと access token。

        Cloud Run の資格情報は、取り直すまでメールが "default" のままなので先に取り直す。
        """
        self._bucket()
        with self._lock:
            credentials = self._credentials
            if credentials is None:
                # client だけを差し替えたとき。鍵を持つ資格情報なら、SDK がそのまま署名する
                return {}
            if not credentials.valid:
                credentials.refresh(Request())  # type: ignore[no-untyped-call]
            return {
                "service_account_email": credentials.service_account_email,  # type: ignore[attr-defined]
                "access_token": str(credentials.token),
            }

    def _put(self, path: str, wav: bytes) -> None:
        self._bucket().blob(path).upload_from_string(wav, content_type="audio/wav")

    async def put(self, path: str, wav: bytes) -> bool:
        try:
            await asyncio.to_thread(self._put, path, wav)
        except (GoogleAPIError, GoogleAuthError):
            logger.exception("audio: could not upload %s", path)
            return False
        return True

    def _url(self, path: str) -> str:
        return str(
            self._bucket()
            .blob(path)
            .generate_signed_url(
                version="v4", expiration=self._url_ttl, method="GET", **self._signer()
            )
        )

    async def url(self, path: str) -> str | None:
        try:
            return await asyncio.to_thread(self._url, path)
        except (GoogleAPIError, GoogleAuthError, AttributeError, ValueError):
            # 署名できない資格情報（手元の利用者の資格情報など）は AttributeError か ValueError
            logger.exception("audio: could not sign a URL for %s", path)
            return None

    def _delete_all(self, prefix: str) -> int:
        bucket = self._bucket()
        blobs = list(bucket.list_blobs(prefix=prefix))
        # 一覧のあとに別の処理が消したものは、もう消えているので気にしない
        bucket.delete_blobs(blobs, on_error=lambda blob: None)
        return len(blobs)

    async def delete_all(self, prefix: str) -> None:
        try:
            deleted = await asyncio.to_thread(self._delete_all, prefix)
        except (GoogleAPIError, GoogleAuthError) as e:
            # 窓口は 502 を返すだけなので、原因はここで残す
            logger.exception("audio: could not delete %s", prefix)
            raise AccountDeleteError from e
        logger.info("audio: deleted %d files under %s", deleted, prefix)


def audio_store(settings: Settings) -> GcsAudioStore | None:
    """設定から作る。AUDIO_BUCKET が空なら None（声にしない）。ここではまだ資格情報を読まない。"""
    if not settings.audio_bucket:
        return None
    return GcsAudioStore(settings.audio_bucket, timedelta(seconds=settings.audio_url_ttl_sec))
