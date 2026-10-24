from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastmcp import Client
from fastmcp.mcp_config import MCPConfig, RemoteMCPServer, StdioMCPServer

OPEN_TIMEOUT = 30.0
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
class McpServerInfo:
    tools: list[McpToolSpec]
    instructions: str = ""


@dataclass(frozen=True)
class McpTarget:
    name: str
    server: StdioMCPServer | RemoteMCPServer

    @property
    def trusted_tools(self) -> frozenset[str]:
        return frozenset((self.server.model_extra or {}).get("trustedTools", []))


def load_config(path: Path) -> MCPConfig:
    return MCPConfig.from_file(path) if path.is_file() else MCPConfig()


def config_targets(config: MCPConfig, workspace: Path) -> dict[str, McpTarget]:
    targets: dict[str, McpTarget] = {}
    for name, server in config.mcpServers.items():
        if isinstance(server, StdioMCPServer):
            server = server.model_copy(
                update={"cwd": str(workspace / (server.cwd or "."))}
            )
        targets[f"config:{name}"] = McpTarget(name=name, server=server)
    return targets


class McpSession:
    def __init__(self, target: McpTarget) -> None:
        self.target = target
        self._client = Client(
            target.server.to_transport(),
            timeout=CALL_TIMEOUT,
            init_timeout=OPEN_TIMEOUT,
        )

    async def open(self) -> McpServerInfo:
        try:
            await self._client.__aenter__()
        except Exception as exc:
            raise McpError(str(exc)) from exc
        try:
            tools = await self._client.list_tools()
        except Exception as exc:
            await self._client.close()
            raise McpError(str(exc)) from exc
        trusted = self.target.trusted_tools
        return McpServerInfo(
            tools=[
                McpToolSpec(
                    name=tool.name,
                    description=tool.description or "",
                    input_schema=dict(tool.input_schema or {}),
                    read_only=bool(tool.annotations and tool.annotations.read_only_hint)
                    or tool.name in trusted,
                )
                for tool in tools
            ],
            instructions=(self._client.instructions or "").strip(),
        )

    async def call(self, tool: str, arguments: dict[str, Any]) -> str:
        try:
            result = await self._client.call_tool(tool, arguments)
        except Exception as exc:
            raise McpError(str(exc)) from exc
        return "\n".join(
            getattr(item, "text", None) or f"[{item.type}]" for item in result.content
        ).strip()

    async def close(self) -> None:
        await self._client.close()


async def discover(target: McpTarget) -> McpServerInfo:
    session = McpSession(target)
    info = await session.open()
    await session.close()
    return info


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
