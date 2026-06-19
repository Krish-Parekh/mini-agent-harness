from __future__ import annotations

import re
import time
from typing import Any

import httpx
from pydantic import Field

from miniagent.sandbox.base import Sandbox
from miniagent.schema import Action, Observation
from miniagent.tools.base import Tool

_DEFAULT_TIMEOUT = 20.0
_TAG_RE = re.compile(r"<[^>]+>")


class FetchUrlAction(Action):
    url: str = Field(description="The HTTP or HTTPS URL to fetch.")
    max_chars: int = Field(
        default=8_000,
        ge=500,
        le=20_000,
        description="Maximum characters of page text to return.",
    )


class FetchUrlObservation(Observation):
    url: str
    content: str
    error: bool = False
    duration_ms: int = 0

    def to_llm_text(self) -> str:
        if self.error:
            return self.content
        return f"url: {self.url}\ncontent:\n{self.content}"

    def ui_details(self) -> dict[str, Any] | None:
        return {
            "url": self.url,
            "method": "GET",
        }


def _html_to_text(html: str) -> str:
    text = _TAG_RE.sub(" ", html)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


class FetchUrlTool(Tool):
    name = "fetch_url"
    description = (
        "Fetch readable text from a public URL. Use this after `web_search` when "
        "you have a specific link and need more page content. This is a lightweight "
        "HTTP fetch — it may fail on JS-heavy pages, login walls, or bot protection."
    )
    action_type = FetchUrlAction
    observation_type = FetchUrlObservation

    def execute(self, action: FetchUrlAction, _sandbox: Sandbox) -> FetchUrlObservation:
        started = time.perf_counter()
        url = action.url.strip()
        if not url.startswith(("http://", "https://")):
            return FetchUrlObservation(
                url=url,
                content="ERROR: fetch_url only supports http:// and https:// URLs.",
                error=True,
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
        try:
            with httpx.Client(
                timeout=_DEFAULT_TIMEOUT,
                follow_redirects=True,
            ) as client:
                response = client.get(url)
                response.raise_for_status()
                content_type = response.headers.get("content-type", "")
                body = response.text
        except Exception as exc:
            duration_ms = int((time.perf_counter() - started) * 1000)
            return FetchUrlObservation(
                url=url,
                content=f"ERROR: fetch failed: {exc}",
                error=True,
                duration_ms=duration_ms,
            )

        if "html" in content_type.lower():
            body = _html_to_text(body)
        body = body.strip()
        if len(body) > action.max_chars:
            body = body[: action.max_chars] + "\n...(truncated)"
        duration_ms = int((time.perf_counter() - started) * 1000)
        if not body:
            return FetchUrlObservation(
                url=url,
                content="ERROR: fetched page had no readable text.",
                error=True,
                duration_ms=duration_ms,
            )
        return FetchUrlObservation(
            url=url,
            content=body,
            duration_ms=duration_ms,
        )
