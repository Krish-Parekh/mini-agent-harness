from __future__ import annotations

from miniagent.llm import _supports_custom_temperature


def test_gpt_5_models_use_default_temperature():
    assert not _supports_custom_temperature("gpt-5.5")
    assert not _supports_custom_temperature("gpt-5.5-pro")
    assert not _supports_custom_temperature("gpt-5.5-2026-04-23")
    assert not _supports_custom_temperature("openai/gpt-5.5")


def test_non_gpt_5_models_keep_custom_temperature():
    assert _supports_custom_temperature("gpt-4o-mini")
    assert _supports_custom_temperature("gpt-4.1")
