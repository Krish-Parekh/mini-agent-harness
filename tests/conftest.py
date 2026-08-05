from __future__ import annotations

import uuid
from dataclasses import dataclass

import pytest

from backend.core.jwt import Claims, InvalidToken


@dataclass
class StubVerifier:

    tokens: dict[str, Claims]

    def verify(self, token: str) -> Claims:
        try:
            return self.tokens[token]
        except KeyError:
            raise InvalidToken("unknown test token") from None


@pytest.fixture
def user_a() -> Claims:
    return Claims(
        sub=str(uuid.uuid4()), email="a@example.com", avatar_url="https://a.png"
    )


@pytest.fixture
def user_b() -> Claims:
    return Claims(sub=str(uuid.uuid4()), email="b@example.com", avatar_url=None)


@pytest.fixture
def verifier(user_a: Claims, user_b: Claims) -> StubVerifier:
    return StubVerifier({"token-a": user_a, "token-b": user_b})
