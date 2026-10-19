from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from typing import Any

import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

DISCOVER_TIMEOUT = 15.0
CALL_TIMEOUT = 120.0


class McpError(Exception):
    pass


@dataclass(frozen=True)
class McpToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    read_only: bool = False


@dataclass(frozen=True)
class McpTarget:
    name: str
    url: str
    auth_header: str | None = None
    auth_value: str | None = None

    def headers(self) -> dict[str, str]:
        if self.auth_header and self.auth_value:
            return {self.auth_header: self.auth_value}
        return {}


async def discover(target: McpTarget) -> list[McpToolSpec]:
    try:
        async with asyncio.timeout(DISCOVER_TIMEOUT):
            client = httpx2.AsyncClient(headers=target.headers())
            async with client:
                async with streamable_http_client(
                    target.url, http_client=client
                ) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        result = await session.list_tools()
    except Exception as exc:
        raise McpError(str(exc)) from exc

    return [
        McpToolSpec(
            name=tool.name,
            description=tool.description or "",
            input_schema=dict(tool.input_schema or {}),
            read_only=bool(tool.annotations and tool.annotations.read_only_hint),
        )
        for tool in result.tools
    ]


async def call(target: McpTarget, tool: str, arguments: dict[str, Any]) -> str:
    try:
        async with asyncio.timeout(CALL_TIMEOUT):
            client = httpx2.AsyncClient(headers=target.headers())
            async with client:
                async with streamable_http_client(
                    target.url, http_client=client
                ) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        result = await session.call_tool(tool, arguments)
    except Exception as exc:
        raise McpError(str(exc)) from exc

    return _render(result)


def _render(result: Any) -> str:
    parts: list[str] = []
    for item in getattr(result, "content", []) or []:
        text = getattr(item, "text", None)
        if text is not None:
            parts.append(text)
            continue
        parts.append(f"[{getattr(item, 'type', 'content')}]")
    rendered = "\n".join(parts).strip()
    if getattr(result, "is_error", False):
        raise McpError(rendered or "tool reported an error")
    return rendered


class McpBridge:
    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        with self._lock:
            if self._loop is not None:
                return self._loop
            loop = asyncio.new_event_loop()
            thread = threading.Thread(
                target=loop.run_forever, name="mcp-bridge", daemon=True
            )
            thread.start()
            self._loop = loop
            self._thread = thread
            return loop

    def run(self, coro) -> Any:
        loop = self._ensure_loop()
        return asyncio.run_coroutine_threadsafe(coro, loop).result()


bridge = McpBridge()
