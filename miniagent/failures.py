from __future__ import annotations

import re
import time
from typing import Literal

import litellm
from pydantic import BaseModel, ConfigDict

FailureKind = Literal[
    "usage_limit", "provider_error", "transport_error", "permission_error", "validation_error"
]

MAX_DETAIL_CHARS = 500

_KINDS: tuple[tuple[tuple[type[Exception], ...], FailureKind, bool], ...] = (
    ((litellm.RateLimitError,), "usage_limit", True),
    ((litellm.AuthenticationError, litellm.PermissionDeniedError), "permission_error", False),
    ((litellm.Timeout, litellm.APIConnectionError), "transport_error", True),
    (
        (litellm.BadRequestError, litellm.UnprocessableEntityError, litellm.NotFoundError),
        "validation_error",
        False,
    ),
    (
        (
            litellm.InternalServerError,
            litellm.ServiceUnavailableError,
            litellm.BadGatewayError,
            litellm.APIError,
        ),
        "provider_error",
        True,
    ),
)

_SECRETS = (
    (re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+"), "Bearer ***"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{8,}"), "sk-***"),
    (re.compile(r"(?i)(https?://)[^\s/@:]+:[^\s/@]+@"), r"\1***@"),
)


class ProviderFailure(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: FailureKind
    retryable: bool
    reset_at: float | None = None


def redact(text: str) -> str:
    for pattern, replacement in _SECRETS:
        text = pattern.sub(replacement, text)
    return text[:MAX_DETAIL_CHARS]


def classify(exc: Exception) -> ProviderFailure | None:
    for types, kind, retryable in _KINDS:
        if isinstance(exc, types):
            return ProviderFailure(kind=kind, retryable=retryable, reset_at=_reset_at(exc))
    return None


def _reset_at(exc: Exception) -> float | None:
    response = getattr(exc, "response", None)
    retry_after = getattr(response, "headers", {}).get("retry-after")
    try:
        return time.time() + float(retry_after)
    except (TypeError, ValueError):
        return None
