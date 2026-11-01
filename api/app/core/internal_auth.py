"""内部の窓口（/internal）の呼び出し元を確かめる。

api は利用者のために公開している（--allow-unauthenticated）ので、Cloud Run の手前では
止められない。Cloud Scheduler と Cloud Tasks には、決めたサービスアカウントの OIDC
トークンを付けて呼ばせ、ここで署名・宛先・メールアドレスを検証する。
X-CloudTasks-* のヘッダは外から付けられるので、判定に使わない。
"""

import logging
from functools import lru_cache
from typing import Annotated, Any, Protocol

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from app.core.auth import InvalidTokenError
from app.core.config import get_settings

logger = logging.getLogger(__name__)


class InternalCallerVerifier(Protocol):
    def verify(self, token: str) -> None: ...


class GoogleOidcVerifier:
    def __init__(self, audience: str, caller_email: str) -> None:
        self._audience = audience
        self._caller_email = caller_email
        # 公開鍵の取得に使う。セッションを使い回して接続を張り直さない
        self._request = google_requests.Request()

    def verify(self, token: str) -> None:
        if not self._audience or not self._caller_email:
            # 設定がなければ誰も通さない。手元や CI で内部の窓口が開いたままにならないように
            raise InvalidTokenError("internal callers are not configured")
        try:
            claims: dict[str, Any] = id_token.verify_oauth2_token(  # type: ignore[no-untyped-call]
                token, self._request, audience=self._audience
            )
        except ValueError as e:
            raise InvalidTokenError from e
        if claims.get("email") != self._caller_email or claims.get("email_verified") is not True:
            raise InvalidTokenError(f"unexpected caller: {claims.get('email')}")


@lru_cache
def get_internal_caller_verifier() -> InternalCallerVerifier:
    """プロセスで 1 つ。テストではこの依存を偽物に差し替える。"""
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
