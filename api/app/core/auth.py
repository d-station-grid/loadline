from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated, Protocol

import firebase_admin
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from firebase_admin import auth as firebase_auth
from firebase_admin import credentials as firebase_credentials
from google.auth.credentials import AnonymousCredentials

from app.core.config import get_settings


@dataclass(frozen=True)
class Identity:
    """検証ずみの ID トークンから取り出した身元。"""

    uid: str
    email: str


class InvalidTokenError(Exception):
    """トークンが検証を通らなかった。期限切れ、署名の不正、別プロジェクトのもの。"""


class TokenVerifier(Protocol):
    def verify(self, token: str) -> Identity: ...


class _NoCredential(firebase_credentials.Base):  # type: ignore[misc]
    """ID トークンの検証は Google の公開鍵だけで済む。ADC を読みに行かない空の資格情報。"""

    def get_credential(self) -> AnonymousCredentials:
        return AnonymousCredentials()  # type: ignore[no-untyped-call]


class FirebaseTokenVerifier:
    def __init__(self, project_id: str) -> None:
        # SDK は初期化のときに資格情報を読む。検証だけなら要らないので空のものを渡し、
        # 認証情報のない環境（CI など）でも同じ動きにする。
        # 利用者の管理など Google に認証が要る機能を使うときは ApplicationDefault に替える
        self._app = firebase_admin.initialize_app(
            _NoCredential(), options={"projectId": project_id}
        )

    def verify(self, token: str) -> Identity:
        try:
            claims = firebase_auth.verify_id_token(token, app=self._app)
        except (ValueError, firebase_auth.InvalidIdTokenError) as e:
            raise InvalidTokenError from e
        return Identity(uid=claims["uid"], email=claims.get("email", ""))


@lru_cache
def get_token_verifier() -> TokenVerifier:
    """プロセスで 1 つ。テストではこの依存を偽物に差し替える。"""
    return FirebaseTokenVerifier(get_settings().firebase_project_id)


_bearer = HTTPBearer(auto_error=False)


def get_identity(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    verifier: Annotated[TokenVerifier, Depends(get_token_verifier)],
) -> Identity:
    """FastAPI の依存。Authorization: Bearer <ID トークン> を検証して身元を返す。"""
    unauthorized = HTTPException(
        status.HTTP_401_UNAUTHORIZED, headers={"WWW-Authenticate": "Bearer"}
    )
    if credentials is None:
        raise unauthorized
    try:
        return verifier.verify(credentials.credentials)
    except InvalidTokenError:
        raise unauthorized from None
