from __future__ import annotations

import json
import logging
import re
from typing import Any, TypeVar

import litellm
import logfire
from litellm import ModelResponse
from pydantic import BaseModel, ConfigDict, Field
from tenacity import (
    RetryCallState,
    Retrying,
    before_sleep_log,
    retry_if_exception_type,
    stop_after_attempt,
)

from miniagent.config import ReasoningEffort
from miniagent.tools.base import Tool, to_openai_schema
from miniagent.tracing import generation_attributes, usage_details

logger = logging.getLogger(__name__)


class ToolCall(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    arguments: dict[str, Any]
    raw_arguments: str | None = None
    parse_error: str | None = None


class TokenUsage(BaseModel):
    model_config = ConfigDict(frozen=True)

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cached_prompt_tokens: int = 0
    cache_creation_tokens: int = 0

    def details(self) -> dict[str, int]:
        return usage_details(
            prompt=self.prompt_tokens,
            completion=self.completion_tokens,
            cache_read=self.cached_prompt_tokens,
            cache_creation=self.cache_creation_tokens,
        )


class ContextOverflow(Exception):
    pass


class LLMResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    usage: TokenUsage = Field(default_factory=TokenUsage)
    cost: float = 0.0
    truncated: bool = False


StructuredResponse = TypeVar("StructuredResponse", bound=BaseModel)


_TRANSIENT = (
    litellm.RateLimitError,
    litellm.APIConnectionError,
    litellm.InternalServerError,
    litellm.ServiceUnavailableError,
    litellm.Timeout,
)

DEFAULT_CONTEXT_WINDOW = 128_000
CACHE_BREAKPOINTS = [
    {"location": "message", "role": "system"},
    {"location": "message", "index": -2},
]


def _supports_custom_temperature(model: str) -> bool:
    normalized = model.rsplit("/", 1)[-1]
    if re.match(r"gpt-[5-9]", normalized):
        return False
    return not re.match(r"claude-[a-z]+-5", normalized)


class LLM:
    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        num_retries: int = 4,
        backoff: float = 1.0,
        reasoning_effort: ReasoningEffort | None = None,
    ) -> None:
        self.model = model
        self.api_key = api_key
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.num_retries = num_retries
        self.backoff = backoff
        self.reasoning_effort = reasoning_effort

    @property
    def prompt_caching(self) -> bool:
        try:
            return bool(litellm.utils.supports_prompt_caching(self.model))
        except Exception:
            return False

    def complete(
        self,
        messages: list[dict],
        tools: list[Tool] | None = None,
        phase: str = "agent",
        tool_choice: str = "auto",
    ) -> LLMResponse:
        kwargs = self._completion_kwargs(messages)
        if tools:
            kwargs["tools"] = [to_openai_schema(t) for t in tools]
            kwargs["tool_choice"] = tool_choice
        if self.prompt_caching and len(messages) > 2:
            kwargs["cache_control_injection_points"] = CACHE_BREAKPOINTS

        with logfire.span("llm.complete {phase}", phase=phase, model=self.model) as span:
            try:
                raw = self._call_with_retry(kwargs)
            except litellm.ContextWindowExceededError as exc:
                raise ContextOverflow(str(exc)) from exc
            parsed = self._parse(raw)
            span.set_attributes(
                generation_attributes(
                    model=self.model,
                    phase=phase,
                    messages=messages,
                    output={
                        "text": parsed.text,
                        "tool_calls": [
                            {"name": c.name, "arguments": c.arguments}
                            for c in parsed.tool_calls
                        ],
                    },
                    usage=parsed.usage.details(),
                    cost=parsed.cost,
                )
            )
        return parsed

    def complete_structured(
        self,
        messages: list[dict],
        response_model: type[StructuredResponse],
        phase: str = "structured",
    ) -> StructuredResponse:
        kwargs = self._completion_kwargs(messages)
        kwargs["response_format"] = response_model
        with logfire.span("llm.complete {phase}", phase=phase, model=self.model) as span:
            response = self._call_with_retry(kwargs)
            content = response.choices[0].message.content or ""
            usage = self._usage(response)
            span.set_attributes(
                generation_attributes(
                    model=self.model,
                    phase=phase,
                    messages=messages,
                    output=content,
                    usage=usage.details(),
                    cost=self._cost(response),
                )
            )
        return response_model.model_validate_json(content)

    def count_tokens(
        self, messages: list[dict], tools: list[Tool] | None = None
    ) -> int:
        try:
            return litellm.token_counter(
                model=self.model,
                messages=messages,
                tools=[to_openai_schema(t) for t in tools] if tools else None,
                use_default_image_token_count=True,
            )
        except Exception:
            return 0

    def count_text(self, text: str) -> int:
        try:
            return litellm.token_counter(model=self.model, text=text)
        except Exception:
            return 0

    def context_window(self) -> int:
        try:
            info = litellm.get_model_info(self.model)
        except Exception:
            return DEFAULT_CONTEXT_WINDOW
        return info.get("max_input_tokens") or DEFAULT_CONTEXT_WINDOW

    def _completion_kwargs(self, messages: list[dict]) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": self.max_tokens,
        }
        if _supports_custom_temperature(self.model):
            kwargs["temperature"] = self.temperature
        if self.api_key:
            kwargs["api_key"] = self.api_key
        if self.reasoning_effort:
            kwargs["reasoning_effort"] = self.reasoning_effort
        return kwargs

    def _call_with_retry(self, kwargs: dict[str, Any]) -> ModelResponse:
        """Call the model, retrying transient failures.

        ``num_retries`` is retries beyond the first attempt (``num_retries + 1``
        total). Only ``_TRANSIENT`` errors retry; anything else raises at once.
        Waits come from litellm's own ``calculate_retry_after``, as its router
        uses: the provider's ``retry-after`` when it gives one, else jittered
        exponential backoff. ``reraise=True`` surfaces the original exception
        after the final attempt rather than tenacity's ``RetryError``.
        """
        retryer = Retrying(
            stop=stop_after_attempt(self.num_retries + 1),
            wait=self._retry_wait,
            retry=retry_if_exception_type(_TRANSIENT),
            before_sleep=before_sleep_log(logger, logging.WARNING),
            reraise=True,
        )
        return retryer(litellm.completion, **kwargs)

    def _retry_wait(self, state: RetryCallState) -> float:
        error = state.outcome.exception() if state.outcome else None
        headers = getattr(getattr(error, "response", None), "headers", None)
        return self.backoff * litellm.calculate_retry_after(
            remaining_retries=self.num_retries - state.attempt_number + 1,
            max_retries=self.num_retries,
            response_headers=headers,
        )

    @staticmethod
    def _parse(response: ModelResponse) -> LLMResponse:
        choice = response.choices[0]
        message = choice.message
        text = message.content or None

        tool_calls: list[ToolCall] = []
        for tc in message.tool_calls or []:
            raw_arguments = tc.function.arguments or "{}"
            parse_error = None
            try:
                arguments = json.loads(raw_arguments)
            except json.JSONDecodeError as exc:
                arguments = {}
                preview = raw_arguments[:500]
                parse_error = (
                    f"{exc.msg} at line {exc.lineno} column {exc.colno}; "
                    f"raw arguments: {preview}"
                )
            tool_calls.append(
                ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=arguments,
                    raw_arguments=raw_arguments,
                    parse_error=parse_error,
                )
            )

        return LLMResponse(
            text=text,
            tool_calls=tool_calls,
            usage=LLM._usage(response),
            cost=LLM._cost(response),
            truncated=choice.finish_reason == "length",
        )

    @staticmethod
    def _usage(response: ModelResponse) -> TokenUsage:
        raw = getattr(response, "usage", None)
        if raw is None:
            return TokenUsage()
        details = getattr(raw, "prompt_tokens_details", None)
        cached = getattr(details, "cached_tokens", None) or getattr(
            raw, "cache_read_input_tokens", 0
        )
        return TokenUsage(
            prompt_tokens=getattr(raw, "prompt_tokens", 0) or 0,
            completion_tokens=getattr(raw, "completion_tokens", 0) or 0,
            total_tokens=getattr(raw, "total_tokens", 0) or 0,
            cached_prompt_tokens=cached or 0,
            cache_creation_tokens=getattr(raw, "cache_creation_input_tokens", 0) or 0,
        )

    @staticmethod
    def _cost(response: ModelResponse) -> float:
        try:
            return litellm.completion_cost(completion_response=response) or 0.0
        except Exception:
            return 0.0
