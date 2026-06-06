from __future__ import annotations

import json
import time
from typing import Any

import litellm
from litellm import ModelResponse
from pydantic import BaseModel, ConfigDict, Field

from miniagent.tools.base import Tool, to_openai_schema


class ToolCall(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    arguments: dict[str, Any]


class TokenUsage(BaseModel):
    model_config = ConfigDict(frozen=True)

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class LLMResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    usage: TokenUsage = Field(default_factory=TokenUsage)
    cost: float = 0.0


_TRANSIENT = (
    litellm.RateLimitError,
    litellm.APIConnectionError,
    litellm.InternalServerError,
)


class LLM:
    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        num_retries: int = 2,
        backoff: float = 1.0,
    ) -> None:
        self.model = model
        self.api_key = api_key
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.num_retries = num_retries
        self.backoff = backoff

    def complete(
        self, messages: list[dict], tools: list[Tool] | None = None
    ) -> LLMResponse:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if self.api_key:
            kwargs["api_key"] = self.api_key
        if tools:
            kwargs["tools"] = [to_openai_schema(t) for t in tools]
            kwargs["tool_choice"] = "auto"

        response = self._call_with_retry(kwargs)
        return self._parse(response)

    def count_tokens(self, messages: list[dict]) -> int:
        try:
            return litellm.token_counter(model=self.model, messages=messages)
        except Exception:
            return 0

    def _call_with_retry(self, kwargs: dict[str, Any]):
        for attempt in range(self.num_retries + 1):
            try:
                return litellm.completion(**kwargs)
            except _TRANSIENT:
                if attempt == self.num_retries:
                    raise
                time.sleep(self.backoff * (2**attempt))

    @staticmethod
    def _parse(response: ModelResponse) -> LLMResponse:
        message = response.choices[0].message
        text = message.content or None

        tool_calls: list[ToolCall] = []
        for tc in message.tool_calls or []:
            try:
                arguments = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                arguments = {}
            tool_calls.append(
                ToolCall(id=tc.id, name=tc.function.name, arguments=arguments)
            )

        usage = TokenUsage()
        raw = getattr(response, "usage", None)
        if raw is not None:
            usage = TokenUsage(
                prompt_tokens=getattr(raw, "prompt_tokens", 0) or 0,
                completion_tokens=getattr(raw, "completion_tokens", 0) or 0,
                total_tokens=getattr(raw, "total_tokens", 0) or 0,
            )

        try:
            cost = litellm.completion_cost(completion_response=response) or 0.0
        except Exception:
            cost = 0.0

        return LLMResponse(text=text, tool_calls=tool_calls, usage=usage, cost=cost)
