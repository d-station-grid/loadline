import logging
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from fastapi import Depends, FastAPI
from google.auth import crypt, jwt
from httpx import ASGITransport, AsyncClient

from app.core.auth import InvalidTokenError
from app.core.internal_auth import (
    Certs,
    GoogleCerts,
    GoogleOidcVerifier,
    get_internal_caller_verifier,
    require_internal_caller,
)

AUDIENCE = "https://api.example.run.app"
CALLER = "loadline-invoker@loadline-app.iam.gserviceaccount.com"
KEY_ID = "test-key"


def _key_and_cert() -> tuple[bytes, str]:
    """署名の鍵と、Google が公開鍵を配るのと同じ形（X.509 の PEM）の証明書。"""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(1)
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    pem_key = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    return pem_key, cert.public_bytes(serialization.Encoding.PEM).decode()


PEM_KEY, PEM_CERT = _key_and_cert()
# 別の鍵。公開鍵の一覧にない鍵で署名したトークンに使う
OTHER_KEY, _ = _key_and_cert()


def _token(key: bytes = PEM_KEY, **overrides: Any) -> str:
    now = int(time.time())
    claims: dict[str, Any] = {
        "iss": "https://accounts.google.com",
        "aud": AUDIENCE,
        "email": CALLER,
        "email_verified": True,
        "iat": now,
        "exp": now + 3600,
        **overrides,
    }
    signer = crypt.RSASigner.from_string(key, key_id=KEY_ID)  # type: ignore[no-untyped-call]
    token: bytes = jwt.encode(signer, claims)  # type: ignore[no-untyped-call]
    return token.decode()


class Fetches:
    """公開鍵を取った回数を数える偽物。キャッシュしてよい秒数は max_age。"""

    def __init__(self, max_age: int = 3600) -> None:
        self.count = 0
        self.max_age = max_age

    def __call__(self) -> tuple[Certs, int]:
        self.count += 1
        return {KEY_ID: PEM_CERT}, self.max_age


def _verifier(audience: str = AUDIENCE, caller: str = CALLER) -> GoogleOidcVerifier:
    return GoogleOidcVerifier(audience, caller, GoogleCerts(fetch=Fetches()))


def test_accepts_the_callers_token_for_this_audience() -> None:
    _verifier().verify(_token())


@pytest.mark.parametrize(
    ("token", "reason"),
    [
        (_token(key=OTHER_KEY), "signature"),
        (_token(aud="https://someone-else.run.app"), "audience"),
        (_token(exp=int(time.time()) - 3600, iat=int(time.time()) - 7200), "expired"),
        (_token(iss="https://evil.example.com"), "issuer"),
        (_token(email="someone-else@other.iam.gserviceaccount.com"), "caller"),
        (_token(email_verified=False), "caller"),
        ("not-a-jwt", ""),
    ],
    ids=["other-key", "audience", "expired", "issuer", "other-caller", "unverified", "garbage"],
)
def test_rejects_with_the_reason(token: str, reason: str) -> None:
    with pytest.raises(InvalidTokenError) as e:
        _verifier().verify(token)

    # 401 のログに理由が残る
    assert str(e.value)
    assert reason in str(e.value).lower()


@pytest.mark.parametrize(("audience", "caller"), [("", CALLER), (AUDIENCE, "")])
def test_rejects_everyone_when_not_configured(audience: str, caller: str) -> None:
    with pytest.raises(InvalidTokenError):
        _verifier(audience, caller).verify(_token())


def test_keeps_the_certs_while_the_cache_is_fresh() -> None:
    fetches = Fetches(max_age=100)
    now = [1000.0]
    verifier = GoogleOidcVerifier(
        AUDIENCE, CALLER, GoogleCerts(fetch=fetches, clock=lambda: now[0])
    )

    verifier.verify(_token())
    now[0] += 99
    verifier.verify(_token())
    assert fetches.count == 1

    now[0] += 1
    verifier.verify(_token())
    assert fetches.count == 2


@pytest.fixture
def logged_app() -> Iterator[FastAPI]:
    app = FastAPI()

    @app.post("/internal/ping", dependencies=[Depends(require_internal_caller)])
    def ping() -> dict[str, str]:
        return {"ok": "yes"}

    app.dependency_overrides[get_internal_caller_verifier] = _verifier
    yield app


async def test_401_logs_why(logged_app: FastAPI, caplog: pytest.LogCaptureFixture) -> None:
    transport = ASGITransport(app=logged_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with caplog.at_level(logging.WARNING, logger="app.core.internal_auth"):
            res = await client.post(
                "/internal/ping",
                headers={"Authorization": f"Bearer {_token(aud='https://other.run.app')}"},
            )

    assert res.status_code == 401
    assert "rejected a caller (" in caplog.text
    assert "rejected a caller ()" not in caplog.text
    assert "audience" in caplog.text.lower()
