from typing import Any

import pytest

from app.core.auth import InvalidTokenError
from app.core.internal_auth import GoogleOidcVerifier

AUDIENCE = "https://api.example.run.app"
CALLER = "loadline-invoker@loadline-app.iam.gserviceaccount.com"


@pytest.fixture
def claims(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Google の署名の検証を偽物にする。渡された宛先を控え、claims を返す。"""
    returned: dict[str, Any] = {"email": CALLER, "email_verified": True}

    def fake_verify(token: str, _request: Any, audience: str) -> dict[str, Any]:
        if token != "signed":
            raise ValueError("bad signature")
        returned["checked_audience"] = audience
        return returned

    monkeypatch.setattr("app.core.internal_auth.id_token.verify_oauth2_token", fake_verify)
    return returned


def test_accepts_the_callers_token_for_this_audience(claims: dict[str, Any]) -> None:
    GoogleOidcVerifier(AUDIENCE, CALLER).verify("signed")

    assert claims["checked_audience"] == AUDIENCE


def test_rejects_a_bad_signature(claims: dict[str, Any]) -> None:
    with pytest.raises(InvalidTokenError):
        GoogleOidcVerifier(AUDIENCE, CALLER).verify("forged")


def test_rejects_another_service_account(claims: dict[str, Any]) -> None:
    # Google が署名した本物のトークンでも、別のサービスアカウントのものは通さない
    claims["email"] = "someone-else@other-project.iam.gserviceaccount.com"

    with pytest.raises(InvalidTokenError):
        GoogleOidcVerifier(AUDIENCE, CALLER).verify("signed")


def test_rejects_an_unverified_email(claims: dict[str, Any]) -> None:
    claims["email_verified"] = False

    with pytest.raises(InvalidTokenError):
        GoogleOidcVerifier(AUDIENCE, CALLER).verify("signed")


@pytest.mark.parametrize(("audience", "caller"), [("", CALLER), (AUDIENCE, "")])
def test_rejects_everyone_when_not_configured(
    claims: dict[str, Any], audience: str, caller: str
) -> None:
    with pytest.raises(InvalidTokenError):
        GoogleOidcVerifier(audience, caller).verify("signed")
