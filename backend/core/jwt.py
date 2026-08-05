from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import jwt
from jwt import PyJWKClient

_ALGORITHMS = ["ES256", "RS256"]
_AUDIENCE = "authenticated"


class InvalidToken(Exception):
    pass


@dataclass(frozen=True)
class Claims:
    sub: str
    email: str | None
    avatar_url: str | None


class TokenVerifier(Protocol):
    def verify(self, token: str) -> Claims: ...


class SupabaseJWTVerifier:

    def __init__(self, *, supabase_url: str) -> None:
        base = supabase_url.rstrip("/")
        self._issuer = f"{base}/auth/v1"
        self._jwks = (
            PyJWKClient(f"{self._issuer}/.well-known/jwks.json") if base else None
        )

    def verify(self, token: str) -> Claims:
        if self._jwks is None:
            raise InvalidToken("SUPABASE_URL is not configured")
        try:
            key = self._jwks.get_signing_key_from_jwt(token).key
            payload: dict[str, Any] = jwt.decode(
                token,
                key,
                algorithms=_ALGORITHMS,
                audience=_AUDIENCE,
                issuer=self._issuer,
            )
        except Exception as exc:
            raise InvalidToken(str(exc)) from exc
        return _to_claims(payload)


def _to_claims(payload: dict[str, Any]) -> Claims:
    sub = payload.get("sub")
    if not isinstance(sub, str) or not sub:
        raise InvalidToken("token has no subject")
    metadata = payload.get("user_metadata") or {}
    email = payload.get("email") or metadata.get("email")
    avatar = metadata.get("avatar_url")
    return Claims(
        sub=sub,
        email=email if isinstance(email, str) else None,
        avatar_url=avatar if isinstance(avatar, str) else None,
    )
