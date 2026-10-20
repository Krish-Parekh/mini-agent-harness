from __future__ import annotations

import os

import pytest

from miniagent.config import Settings, export_provider_keys
from miniagent.llm import LLM, _supports_custom_temperature


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
