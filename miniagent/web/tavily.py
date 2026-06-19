from __future__ import annotations

import httpx
from pydantic import BaseModel, Field

TAVILY_SEARCH_URL = "https://api.tavily.com/search"
_DEFAULT_TIMEOUT = 30.0


class TavilySearchResult(BaseModel):
    title: str = ""
    url: str
    content: str = ""
    score: float | None = None


class TavilySearchResponse(BaseModel):
    query: str
    results: list[TavilySearchResult] = Field(default_factory=list)
    answer: str | None = None


def tavily_search(
    api_key: str,
    query: str,
    *,
    max_results: int = 5,
    search_depth: str = "basic",
    include_answer: bool = False,
) -> TavilySearchResponse:
    payload = {
        "api_key": api_key,
        "query": query,
        "max_results": max_results,
        "search_depth": search_depth,
        "include_answer": include_answer,
    }
    with httpx.Client(timeout=_DEFAULT_TIMEOUT) as client:
        response = client.post(TAVILY_SEARCH_URL, json=payload)
        response.raise_for_status()
        data = response.json()

    results = [
        TavilySearchResult(
            title=item.get("title") or "",
            url=item["url"],
            content=item.get("content") or "",
            score=item.get("score"),
        )
        for item in data.get("results", [])
        if item.get("url")
    ]
    return TavilySearchResponse(
        query=data.get("query", query),
        results=results,
        answer=data.get("answer"),
    )
