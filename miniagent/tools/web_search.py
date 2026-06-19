from __future__ import annotations

import time
from typing import Any

from pydantic import Field

from miniagent.sandbox.base import Sandbox
from miniagent.schema import Action, Observation
from miniagent.tools.base import Tool
from miniagent.web.tavily import TAVILY_SEARCH_URL, TavilySearchResult, tavily_search


class WebSearchAction(Action):
    query: str = Field(description="The web search query.")
    max_results: int = Field(
        default=5,
        ge=1,
        le=10,
        description="Maximum number of results to return.",
    )


class WebSearchObservation(Observation):
    query: str
    results: list[TavilySearchResult]
    answer: str | None = None
    error: bool = False
    duration_ms: int = 0

    def to_llm_text(self) -> str:
        if self.error:
            return self.query
        lines = [f"query: {self.query}"]
        if self.answer:
            lines.append(f"answer: {self.answer}")
        if not self.results:
            lines.append("(no results)")
            return "\n".join(lines)
        lines.append("results:")
        for index, result in enumerate(self.results, start=1):
            lines.append(f"{index}. {result.title or '(untitled)'}")
            lines.append(f"   url: {result.url}")
            if result.content:
                lines.append(f"   snippet: {result.content}")
        return "\n".join(lines)

    def ui_details(self) -> dict[str, Any] | None:
        return {
            "endpoint": TAVILY_SEARCH_URL,
            "method": "POST",
            "query": self.query,
            "results": [
                {
                    "title": result.title,
                    "url": result.url,
                    "snippet": result.content,
                }
                for result in self.results
            ],
            "answer": self.answer,
        }


class WebSearchTool(Tool):
    name = "web_search"
    description = (
        "Search the public web with Tavily and return titles, URLs, and snippets. "
        "Use this for documentation, API references, changelogs, error messages, "
        "and other information outside the workspace. Prefer `web_research` when you "
        "need a broader investigation with follow-up fetches."
    )
    action_type = WebSearchAction
    observation_type = WebSearchObservation

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def execute(self, action: WebSearchAction, _sandbox: Sandbox) -> WebSearchObservation:
        started = time.perf_counter()
        try:
            response = tavily_search(
                self.api_key,
                action.query,
                max_results=action.max_results,
            )
        except Exception as exc:
            duration_ms = int((time.perf_counter() - started) * 1000)
            return WebSearchObservation(
                query=f"ERROR: web search failed: {exc}",
                results=[],
                error=True,
                duration_ms=duration_ms,
            )
        duration_ms = int((time.perf_counter() - started) * 1000)
        return WebSearchObservation(
            query=response.query,
            results=response.results,
            answer=response.answer,
            duration_ms=duration_ms,
        )
