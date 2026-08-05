from __future__ import annotations

import time
import uuid

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from backend.core.jwt import InvalidToken, SupabaseJWTVerifier

SUPABASE_URL = "https://proj.supabase.co"
ISSUER = f"{SUPABASE_URL}/auth/v1"


def claims(**overrides) -> dict:
    payload = {
        "sub": str(uuid.uuid4()),
        "aud": "authenticated",
        "iss": ISSUER,
        "exp": int(time.time()) + 3600,
        "email": "dev@example.com",
        "user_metadata": {"avatar_url": "https://avatars/1.png"},
    }
    payload.update(overrides)
    return payload


class _StubJWKS:

    def __init__(self, key) -> None:
        self._key = key

    def get_signing_key_from_jwt(self, token: str):
        return type("Key", (), {"key": self._key})()


@pytest.fixture
def signing_key():
    return ec.generate_private_key(ec.SECP256R1())


@pytest.fixture
def jwks_verifier(signing_key) -> SupabaseJWTVerifier:
    verifier = SupabaseJWTVerifier(supabase_url=SUPABASE_URL)
    verifier._jwks = _StubJWKS(signing_key.public_key())
    return verifier


def es256(payload: dict, key) -> str:
    return jwt.encode(payload, key, algorithm="ES256")


def test_accepts_valid_token_and_extracts_claims(jwks_verifier, signing_key):
    payload = claims()
    result = jwks_verifier.verify(es256(payload, signing_key))
    assert result.sub == payload["sub"]
    assert result.email == "dev@example.com"
    assert result.avatar_url == "https://avatars/1.png"


def test_rejects_bad_signature(jwks_verifier):
    other_key = ec.generate_private_key(ec.SECP256R1())
    with pytest.raises(InvalidToken):
        jwks_verifier.verify(es256(claims(), other_key))


def test_rejects_expired(jwks_verifier, signing_key):
    with pytest.raises(InvalidToken):
        jwks_verifier.verify(es256(claims(exp=int(time.time()) - 10), signing_key))


def test_rejects_wrong_audience(jwks_verifier, signing_key):
    with pytest.raises(InvalidToken):
        jwks_verifier.verify(es256(claims(aud="anon"), signing_key))


def test_rejects_wrong_issuer(jwks_verifier, signing_key):
    with pytest.raises(InvalidToken):
        jwks_verifier.verify(es256(claims(iss="https://evil.supabase.co/auth/v1"), signing_key))


def test_rejects_token_without_subject(jwks_verifier, signing_key):
    payload = claims()
    del payload["sub"]
    with pytest.raises(InvalidToken):
        jwks_verifier.verify(es256(payload, signing_key))


def test_rejects_hs256_token(jwks_verifier, signing_key):
    token = jwt.encode(claims(), "a-legacy-shared-secret-of-ample-length", algorithm="HS256")
    with pytest.raises(InvalidToken):
        jwks_verifier.verify(token)


def test_rejects_garbage(jwks_verifier):
    with pytest.raises(InvalidToken):
        jwks_verifier.verify("not-a-jwt")


def test_rejects_everything_when_url_is_unconfigured(signing_key):
    verifier = SupabaseJWTVerifier(supabase_url="")
    with pytest.raises(InvalidToken):
        verifier.verify(es256(claims(), signing_key))
