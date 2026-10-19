from __future__ import annotations

import json
import os

import pytest
from litellm import ModelResponse

from miniagent.config import Settings, export_provider_keys
from miniagent.llm import LLM, _supports_custom_temperature
from miniagent.tracing import (
    generation_attributes,
    tool_result_attributes,
    usage_details,
)


@pytest.mark.parametrize(
    "model,allowed",
    [
        ("anthropic/claude-sonnet-5-5", False),
        ("anthropic/claude-haiku-5-5", False),
        ("claude-opus-5-5", False),
        ("anthropic/claude-sonnet-4-5", True),
        ("gpt-4o-mini", True),
        ("openai/gpt-5-mini", False),
    ],
)
def test_temperature_is_omitted_where_the_model_rejects_it(model, allowed):
    assert _supports_custom_temperature(model) is allowed
    kwargs = LLM(model=model)._completion_kwargs([])
    assert ("temperature" in kwargs) is allowed


def test_claude_is_the_default_with_haiku_for_cheap_calls(monkeypatch):
    for name in ("MINIAGENT_MODEL", "MINIAGENT_POLICY_MODEL"):
        monkeypatch.delenv(name, raising=False)
    settings = Settings(_env_file=None)
    assert settings.model == "anthropic/claude-sonnet-5-5"
    assert settings.policy_model == "anthropic/claude-haiku-5-5"


def test_claude_api_key_is_exported_for_litellm(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("CLAUDE_API_KEY", "sk-test")
    export_provider_keys(Settings(_env_file=None))
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-test"


def test_existing_anthropic_key_is_not_overwritten(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-real")
    monkeypatch.setenv("CLAUDE_API_KEY", "sk-other")
    export_provider_keys(Settings(_env_file=None))
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-real"


def _response(usage: dict) -> ModelResponse:
    return ModelResponse(
        choices=[{"message": {"role": "assistant", "content": "hi"}}],
        usage=usage,
    )


def test_usage_reads_cached_tokens_from_openai_shape():
    usage = LLM._usage(
        _response(
            {
                "prompt_tokens": 1000,
                "completion_tokens": 10,
                "total_tokens": 1010,
                "prompt_tokens_details": {"cached_tokens": 800},
            }
        )
    )
    assert usage.cached_prompt_tokens == 800


def test_usage_reads_anthropic_cache_fields():
    usage = LLM._usage(
        _response(
            {
                "prompt_tokens": 1000,
                "completion_tokens": 10,
                "total_tokens": 1010,
                "cache_read_input_tokens": 600,
                "cache_creation_input_tokens": 300,
            }
        )
    )
    assert usage.cached_prompt_tokens == 600
    assert usage.cache_creation_tokens == 300


def test_langfuse_usage_excludes_cached_tokens_from_input():
    details = usage_details(prompt=1000, completion=10, cache_read=600, cache_creation=300)
    assert details == {
        "input": 100,
        "output": 10,
        "input_cache_read": 600,
        "input_cache_creation": 300,
        "total": 1010,
    }


def test_generation_attributes_mark_a_generation_and_clip_input():
    attributes = generation_attributes(
        model="anthropic/claude-sonnet-5-5",
        phase="step",
        messages=[{"role": "user", "content": "x" * 50_000}],
        output={"text": "ok"},
        usage={"input": 1},
        cost=0.0,
    )
    assert attributes["langfuse.observation.type"] == "generation"
    assert "chars truncated" in attributes["langfuse.observation.input"]
    assert "langfuse.observation.cost_details" not in attributes
    assert json.loads(attributes["langfuse.observation.usage_details"]) == {"input": 1}


def test_failed_tool_results_are_marked_as_errors():
    attributes = tool_result_attributes(
        content="boom", error=True, details={"spill_path": ".miniagent/outputs/a.txt"}
    )
    assert attributes["langfuse.observation.level"] == "ERROR"
    assert attributes["tool.spill_path"] == ".miniagent/outputs/a.txt"


def test_context_window_comes_from_litellm_model_info():
    assert LLM(model="gpt-4.1").context_window() == 1_047_576


def test_unmapped_model_falls_back_to_a_default_window():
    assert LLM(model="made-up/model-x").context_window() == 128_000


def test_token_count_includes_tool_schemas():
    from miniagent.tools.bash import BashTool

    llm = LLM(model="gpt-4o-mini")
    messages = [{"role": "user", "content": "hello"}]
    assert llm.count_tokens(messages, [BashTool()]) > llm.count_tokens(messages)


def test_cache_breakpoints_only_for_models_that_support_caching(monkeypatch):
    import litellm

    captured = {}

    def fake_completion(**kwargs):
        captured.update(kwargs)
        return _response({"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2})

    monkeypatch.setattr(litellm, "completion", fake_completion)
    messages = [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "u"},
        {"role": "user", "content": "<runtime-context>x</runtime-context>"},
    ]

    monkeypatch.setattr(litellm.utils, "supports_prompt_caching", lambda model: True)
    LLM(model="anthropic/claude-sonnet-5-5").complete(messages)
    assert captured["cache_control_injection_points"][1] == {"location": "message", "index": -2}
    assert "num_retries" not in captured

    captured.clear()
    monkeypatch.setattr(litellm.utils, "supports_prompt_caching", lambda model: False)
    LLM(model="gpt-4o-mini").complete(messages)
    assert "cache_control_injection_points" not in captured
