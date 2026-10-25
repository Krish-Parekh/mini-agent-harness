from __future__ import annotations

import os

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

server = MCPServer("tracker", instructions="Search before you create an issue.")


@server.tool(annotations=ToolAnnotations(read_only_hint=True))
def search(query: str) -> str:
    return f"found 2 issues for {query}"


@server.tool()
def create_issue(title: str) -> str:
    return f"created {title}"


@server.tool(annotations=ToolAnnotations(read_only_hint=True))
def pid() -> str:
    return str(os.getpid())


@server.tool()
def fail() -> str:
    raise ToolError("tracker is down")


if __name__ == "__main__":
    server.run("stdio")
