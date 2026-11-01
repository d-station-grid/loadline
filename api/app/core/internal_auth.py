"""内部の窓口（/internal）の呼び出し元を確かめる。

api は利用者のために公開している（--allow-unauthenticated）ので、Cloud Run の手前では
止められない。Cloud Scheduler と Cloud Tasks には、決めたサービスアカウントの OIDC
トークンを付けて呼ばせ、ここで署名・宛先・発行元・メールアドレスを検証する。
X-CloudTasks-* のヘッダは外から付けられるので、判定に使わない。
"""

import logging
import re
import threading
import time
from collections.abc import Callable
from functools import lru_cache
from typing import Annotated, Any, Protocol

import requests
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from google.auth import exceptions as google_exceptions
from google.auth import jwt

from app.core.auth import InvalidTokenError
from app.core.config import get_settings

logger = logging.getLogger(__name__)

# google.oauth2.id_token.verify_oauth2_token と同じ公開鍵と発行元
GOOGLE_CERTS_URL = "https://www.googleapis.com/oauth2/v1/certs"
GOOGLE_ISSUERS = ("accounts.google.com", "https://accounts.google.com")

Certs = dict[str, str]
# 公開鍵と、キャッシュしてよい秒数
CertsFetch = Callable[[], tuple[Certs, int]]


def fetch_google_certs() -> tuple[Certs, int]:
    """Google の公開鍵を取る。呼ぶたびに新しい接続で取り、Session を共有しない。"""
    res = requests.get(GOOGLE_CERTS_URL, timeout=10)
    res.raise_for_status()
    found = re.search(r"max-age=(\d+)", res.headers.get("Cache-Control", ""))
    certs: Certs = res.json()
    return certs, int(found.group(1)) if found else 0


class GoogleCerts:
    """Google の公開鍵を、応答の Cache-Control の max-age の間だけ持つ。

    Tasks は窓口を並べて呼ぶので、取り直しは lock で 1 本にまとめる。
    """

    def __init__(
        self, fetch: CertsFetch = fetch_google_certs, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._fetch = fetch
        self._clock = clock
        self._lock = threading.Lock()
        self._certs: Certs | None = None
        self._expires_at = 0.0

    def get(self) -> Certs:
        with self._lock:
            if self._certs is None or self._clock() >= self._expires_at:
                certs, max_age = self._fetch()
                self._certs, self._expires_at = certs, self._clock() + max_age
            return self._certs


class InternalCallerVerifier(Protocol):
    def verify(self, token: str) -> None: ...


class GoogleOidcVerifier:
    def __init__(self, audience: str, caller_email: str, certs: GoogleCerts | None = None) -> None:
        self._audience = audience
        self._caller_email = caller_email
        self._certs = certs or GoogleCerts()

    def verify(self, token: str) -> None:
        if not self._audience or not self._caller_email:
            # 設定がなければ誰も通さない。手元や CI で内部の窓口が開いたままにならないように
            raise InvalidTokenError("internal callers are not configured")
        try:
            # 署名、宛先、期限を確かめる
            claims: dict[str, Any] = jwt.decode(  # type: ignore[no-untyped-call]
                token, certs=self._certs.get(), audience=self._audience
            )
        except (ValueError, google_exceptions.GoogleAuthError) as e:
            raise InvalidTokenError(str(e)) from e
        if claims.get("iss") not in GOOGLE_ISSUERS:
            raise InvalidTokenError(f"unexpected issuer: {claims.get('iss')}")
        if claims.get("email") != self._caller_email or claims.get("email_verified") is not True:
            raise InvalidTokenError(f"unexpected caller: {claims.get('email')}")


@lru_cache
def get_internal_caller_verifier() -> InternalCallerVerifier:
    """プロセスで 1 つ（公開鍵のキャッシュも 1 つ）。テストではこの依存を偽物に差し替える。"""
    settings = get_settings()
    return GoogleOidcVerifier(settings.internal_audience, settings.internal_caller_email)


_bearer = HTTPBearer(auto_error=False)


def require_internal_caller(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    verifier: Annotated[InternalCallerVerifier, Depends(get_internal_caller_verifier)],
) -> None:
    """FastAPI の依存。Scheduler か Tasks からの呼び出しでなければ 401。"""
    unauthorized = HTTPException(
        status.HTTP_401_UNAUTHORIZED, headers={"WWW-Authenticate": "Bearer"}
    )
    if credentials is None:
        raise unauthorized
    try:
        verifier.verify(credentials.credentials)
    except InvalidTokenError as e:
        logger.warning("internal: rejected a caller (%s)", e)
        raise unauthorized from None
