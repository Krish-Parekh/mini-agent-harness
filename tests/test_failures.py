from __future__ import annotations

import time

import httpx
import litellm
import pytest

from miniagent.failures import MAX_DETAIL_CHARS, classify, redact


def _response(status: int, headers: dict | None = None) -> httpx.Response:
    return httpx.Response(
        status, headers=headers, request=httpx.Request("POST", "https://api.example.com")
    )


@pytest.mark.parametrize(
    ("exc", "kind", "retryable"),
    [
        (litellm.RateLimitError("slow down", "anthropic", "claude", response=_response(429)), "usage_limit", True),
        (litellm.AuthenticationError("bad key", "anthropic", "claude"), "permission_error", False),
        (litellm.APIConnectionError("reset", "anthropic", "claude"), "transport_error", True),
        (litellm.BadRequestError("bad", "claude", "anthropic"), "validation_error", False),
        (litellm.InternalServerError("oops", "anthropic", "claude"), "provider_error", True),
    ],
)
def test_provider_errors_are_classified(exc, kind, retryable):
    failure = classify(exc)
    assert failure is not None
    assert (failure.kind, failure.retryable) == (kind, retryable)


def test_a_rate_limit_carries_its_reset_time():
    exc = litellm.RateLimitError(
        "slow down", "anthropic", "claude", response=_response(429, {"retry-after": "30"})
    )
    failure = classify(exc)
    assert failure.reset_at == pytest.approx(time.time() + 30, abs=5)


def test_non_provider_errors_are_not_classified():
    assert classify(ValueError("boom")) is None


def test_a_failed_step_records_the_typed_failure_without_secrets():
    from miniagent.events import ErrorEvent
    from tests.test_agent_history import QueueLLM, _conversation

    class LimitedLLM(QueueLLM):
        def complete(self, messages, tools=None, phase="agent"):
            raise litellm.RateLimitError(
                "limit for key sk-ant-api03-SECRETSECRET", "anthropic", "claude", response=_response(429)
            )

    conversation, _ = _conversation(LimitedLLM())
    conversation.send_message("hi")
    conversation.run()

    [error] = [e for e in conversation.events if isinstance(e, ErrorEvent)]
    assert error.failure.kind == "usage_limit"
    assert "SECRETSECRET" not in error.message
    assert conversation.status.value == "error"


def test_secrets_are_redacted_and_detail_is_capped():
    text = (
        "Authorization: Bearer abc.def-123 key sk-ant-api03-SECRETSECRET "
        "url https://user:pass@example.com/x " + "x" * 2000
    )
    cleaned = redact(text)
    assert "abc.def-123" not in cleaned and "SECRETSECRET" not in cleaned
    assert "user:pass" not in cleaned
    assert "Bearer ***" in cleaned and "sk-***" in cleaned and "https://***@example.com" in cleaned
    assert len(cleaned) == MAX_DETAIL_CHARS
