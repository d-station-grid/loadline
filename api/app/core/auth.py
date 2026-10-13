from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated, Protocol

import firebase_admin
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from firebase_admin import auth as firebase_auth

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


class FirebaseTokenVerifier:
    def __init__(self, project_id: str) -> None:
        # projectId を渡すと、検証だけなら認証情報なしで動く
        self._app = firebase_admin.initialize_app(options={"projectId": project_id})

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
