"""週次レビューの音声を Cloud Storage に置く、署名付き URL を出す、消す。

バケットは非公開。web には期限つきの署名付き URL を渡し、ブラウザはそれで直接読む。
Cloud Run には鍵のファイルがないので、署名は IAM の signBlob に頼む。本番は Cloud Run の
サービスアカウント（loadline-api）で、バケットの objectUser と、自身の
serviceAccountTokenCreator が要る。

SDK は同期なので、別のスレッドで待つ。別のスレッドは途中で止められないので、どの通信にも
SDK の側で上限を渡す。週次レビューを作る処理は DB の行を持ったまま置くので、Tasks の待ち時間
（180 秒）の中で、音声なしに切り替えられるようにする。

資格情報を読むのは初めて使うときなので、CI など資格情報のない環境でも起動や import では
落ちない。
"""

import asyncio
import logging
import threading
from datetime import timedelta
from typing import Any

import google.auth
from google.api_core.exceptions import GoogleAPIError
from google.auth import iam
from google.auth.credentials import Credentials, Signing
from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import Request
from google.cloud import storage  # type: ignore[attr-defined]
from google.cloud.storage.retry import DEFAULT_RETRY

from app.core.config import Settings
from app.services.accounts import AccountDeleteError

logger = logging.getLogger(__name__)

_SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]

# 置く・一覧・消す の 1 回の通信の上限と、やり直しを含めた上限。SDK の既定（60 秒と 120 秒）
# では、Gemini・Jev・tts の最大 135 秒に足すと Tasks の 180 秒を超える
STORAGE_TIMEOUT_SEC = 10.0
STORAGE_RETRY_SEC = 20.0
# 署名を待つ上限。超えたら URL なし（文字だけ）で返す。普段は 0.1 秒ほど
SIGN_TIMEOUT_SEC = 5.0


class _TimedRequest:
    """どの通信にも上限を付ける request。google-auth の既定は 1 回 120 秒。"""

    def __init__(self, timeout_sec: float) -> None:
        self._request = Request()
        self._timeout_sec = timeout_sec

    def __call__(self, url: str, method: str = "GET", **kwargs: Any) -> Any:
        kwargs["timeout"] = self._timeout_sec
        return self._request(url, method=method, **kwargs)


class _IamSigning(Signing):
    """IAM の signBlob で署名する。SDK に渡すと、鍵の代わりにこれで署名する。

    SDK が自分で signBlob を呼ぶ形（メールと access token を渡す）では、通信の上限を
    決められないので、google-auth の iam.Signer に上限つきの request を渡す。
    """

    def __init__(self, credentials: Credentials, email: str, timeout_sec: float) -> None:
        self._email = email
        self._signer = iam.Signer(_TimedRequest(timeout_sec), credentials, email)  # type: ignore[no-untyped-call]

    @property
    def signer(self) -> iam.Signer:
        return self._signer

    @property
    def signer_email(self) -> str:
        return self._email

    def sign_bytes(self, message: bytes) -> bytes:
        return self._signer.sign(message)  # type: ignore[no-any-return]


class GcsAudioStore:
    def __init__(
        self,
        bucket: str,
        url_ttl: timedelta,
        credentials: Credentials | None = None,
        client: Any = None,
        sign_timeout_sec: float = SIGN_TIMEOUT_SEC,
    ) -> None:
        """credentials と client と sign_timeout_sec は、テストで差し替える。"""
        self._bucket_name = bucket
        self._url_ttl = url_ttl
        self._credentials = credentials
        self._client = client
        self._sign_timeout_sec = sign_timeout_sec
        self._signing: _IamSigning | None = None
        self._lock = threading.Lock()

    def _bucket(self) -> Any:
        with self._lock:
            if self._client is None:
                project = None
                if self._credentials is None:
                    self._credentials, project = google.auth.default(scopes=_SCOPES)
                self._client = storage.Client(project=project, credentials=self._credentials)
            return self._client.bucket(self._bucket_name)

    def _iam_signing(self) -> _IamSigning:
        """IAM で署名する資格情報。初めて署名するときに 1 回だけ作る。

        Cloud Run の資格情報は、取り直すまでメールが "default" のままなので先に取り直す。
        手元の利用者の資格情報にはメールがないので AttributeError になる。
        """
        self._bucket()
        with self._lock:
            if self._signing is None:
                credentials = self._credentials
                if credentials is None:
                    raise AttributeError("no credentials to sign with")
                if not credentials.valid:
                    credentials.refresh(_TimedRequest(self._sign_timeout_sec))  # type: ignore[no-untyped-call]
                email = credentials.service_account_email  # type: ignore[attr-defined]
                self._signing = _IamSigning(credentials, email, self._sign_timeout_sec)
            return self._signing

    @staticmethod
    def _limits() -> dict[str, Any]:
        return {
            "timeout": STORAGE_TIMEOUT_SEC,
            "retry": DEFAULT_RETRY.with_timeout(STORAGE_RETRY_SEC),
        }

    def _put(self, path: str, wav: bytes) -> None:
        self._bucket().blob(path).upload_from_string(
            wav, content_type="audio/wav", **self._limits()
        )

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
                version="v4",
                expiration=self._url_ttl,
                method="GET",
                credentials=self._iam_signing(),
            )
        )

    async def url(self, path: str) -> str | None:
        """署名付き URL。署名できない、または SIGN_TIMEOUT_SEC を超えたら None。

        None は「音声がない」とは限らない。次に読むときには URL が出ることがある。
        """
        try:
            async with asyncio.timeout(self._sign_timeout_sec):
                return await asyncio.to_thread(self._url, path)
        except TimeoutError:
            # 別のスレッドの署名は止まらないが、通信ごとの上限でいずれ終わる
            logger.warning(
                "audio: gave up signing %s after %s seconds", path, self._sign_timeout_sec
            )
            return None
        except (GoogleAPIError, GoogleAuthError, AttributeError, ValueError):
            # 署名できない資格情報（手元の利用者の資格情報など）は AttributeError か ValueError
            logger.exception("audio: could not sign a URL for %s", path)
            return None

    def _delete_all(self, prefix: str) -> int:
        bucket = self._bucket()
        blobs = list(bucket.list_blobs(prefix=prefix, **self._limits()))
        # 一覧のあとに別の処理が消したものは、もう消えているので気にしない
        bucket.delete_blobs(blobs, on_error=lambda blob: None, **self._limits())
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
