from __future__ import annotations


def clip(text: str, limit: int) -> str:
    """Clip long text to ~`limit` chars, keeping head + tail with a marker so a
    single huge tool output can't blow the LLM context window."""
    if len(text) <= limit:
        return text
    head = limit * 2 // 3
    tail = limit - head
    omitted = len(text) - head - tail
    return f"{text[:head]}\n… [{omitted} characters truncated] …\n{text[-tail:]}"
