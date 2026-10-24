from __future__ import annotations

import asyncio
import re
import uuid
from pathlib import Path
from urllib.parse import quote

import httpx
from fastmcp.mcp_config import MCPConfig, RemoteMCPServer

from backend.models import McpConnectionRow, SkillRow
from backend.repository import (
    GitHubConnectionRepository,
    McpConnectionRepository,
    SkillRepository,
)
from backend.runtime import mcp as mcp_client
from miniagent import skills_registry
from miniagent.skills_registry import SkillHit

MAX_SKILL_BYTES = 256 * 1024
IMPORT_TIMEOUT = 10.0
MAX_REDIRECTS = 3
ALLOWED_PREFIXES = ("text/", "application/json")
SKILL_CATALOG_BUDGET_CHARS = 2_000
SKILL_DESCRIPTION_MAX_CHARS = 200
MCP_INSTRUCTIONS_MAX_CHARS = 1_000
MAX_SKILL_CANDIDATES = 10
GITHUB_API = "https://api.github.com"
RAW_GITHUB = "https://raw.githubusercontent.com"

_REPO_NAME = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
_SKILL_ID = re.compile(r"[A-Za-z0-9_.:@-]+")


class ImportError_(Exception):
    pass


def _check_response(response: httpx.Response) -> None:
    if response.status_code >= 400:
        raise ImportError_(f"The URL returned HTTP {response.status_code}.")
    if response.url.scheme != "https":
        raise ImportError_("The URL redirected away from https.")
    content_type = response.headers.get("content-type", "").split(";")[0].strip()
    if not content_type.startswith(ALLOWED_PREFIXES):
        raise ImportError_(f"Unsupported content type: {content_type or 'none'}.")


async def _read_capped(response: httpx.Response) -> bytes:
    body = bytearray()
    async for chunk in response.aiter_bytes():
        body.extend(chunk)
        if len(body) > MAX_SKILL_BYTES:
            raise ImportError_("The skill is larger than 256 KB.")
    return bytes(body)


def _frontmatter(body: str) -> dict[str, str]:
    if not body.startswith("---"):
        return {}
    end = body.find("\n---", 3)
    if end == -1:
        return {}
    fields: dict[str, str] = {}
    for line in body[3:end].splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip() in ("name", "description"):
            fields[key.strip()] = value.strip().strip("\"'")
    return fields


def describe_skill(body: str) -> str:
    fields = _frontmatter(body)
    if fields.get("description"):
        return fields["description"][:SKILL_DESCRIPTION_MAX_CHARS]
    text = body
    if fields or body.startswith("---"):
        end = body.find("\n---", 3)
        text = body[end + 4 :] if end != -1 else body
    for paragraph in text.split("\n\n"):
        lines = [
            line.strip()
            for line in paragraph.strip().splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        if lines:
            return " ".join(" ".join(lines).split())[:SKILL_DESCRIPTION_MAX_CHARS]
    return ""


def _valid_repo(name: str) -> bool:
    return bool(_REPO_NAME.fullmatch(name)) and ".." not in name


def _github_headers(token: str | None) -> dict[str, str]:
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _candidate_paths(tree: list[dict], skill_id: str) -> tuple[str | None, list[str]]:
    paths = [
        item["path"]
        for item in tree
        if item.get("type") == "blob"
        and (item.get("path") == "SKILL.md" or item.get("path", "").endswith("/SKILL.md"))
    ]
    for path in paths:
        if path == f"{skill_id}/SKILL.md" or path.endswith(f"/{skill_id}/SKILL.md"):
            return path, []

    def rank(path: str) -> tuple[int, bool, str]:
        folder = path.rsplit("/", 2)[-2] if "/" in path else ""
        return path.count("/"), not (folder and folder in skill_id), path

    return None, sorted(paths, key=rank)[:MAX_SKILL_CANDIDATES]


class SkillService:

    def __init__(
        self,
        skills: SkillRepository,
        connections: GitHubConnectionRepository | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._skills = skills
        self._connections = connections
        self._transport = transport

    async def search(self, query: str) -> list[SkillHit]:
        try:
            return await asyncio.to_thread(skills_registry.search, query)
        except skills_registry.RegistryError as exc:
            raise ImportError_(str(exc)) from None

    async def install(
        self, user_id: uuid.UUID, source: str, skill_id: str, repo: str
    ) -> SkillRow:
        if not (_valid_repo(source) and _valid_repo(repo)):
            raise ImportError_("Repositories must look like owner/name.")
        if not _SKILL_ID.fullmatch(skill_id):
            raise ImportError_(f"Invalid skill id: {skill_id}.")
        token = (
            await self._connections.token_for(user_id) if self._connections else None
        )
        try:
            async with httpx.AsyncClient(
                timeout=IMPORT_TIMEOUT,
                follow_redirects=True,
                max_redirects=MAX_REDIRECTS,
                transport=self._transport,
                headers=_github_headers(token),
            ) as client:
                body = await self._find_skill_body(client, source, skill_id)
        except httpx.HTTPError as exc:
            raise ImportError_(f"Could not fetch the skill: {exc}") from exc

        registry_id = f"{source}/{skill_id}"
        name = _frontmatter(body).get("name") or skill_id
        owned = await self._skills.list_for_user(user_id)
        if any(r.name == name and r.registry_id != registry_id for r in owned):
            name = registry_id
        row = await self._skills.upsert_registry(
            user_id=user_id,
            registry_id=registry_id,
            name=name,
            description=describe_skill(body),
            body=body,
            source_url=skills_registry.page_url(registry_id),
        )
        await self._skills.set_repo_enabled(user_id, repo, row.id, True)
        return row

    async def _find_skill_body(
        self, client: httpx.AsyncClient, source: str, skill_id: str
    ) -> str:
        response = await client.get(
            f"{GITHUB_API}/repos/{source}/git/trees/HEAD", params={"recursive": "1"}
        )
        if response.status_code >= 400:
            raise ImportError_(
                f"GitHub returned HTTP {response.status_code} for {source}."
            )
        path, candidates = _candidate_paths(response.json().get("tree") or [], skill_id)
        if path is not None:
            return await self._fetch_raw(client, source, path)
        for candidate in candidates:
            body = await self._fetch_raw(client, source, candidate)
            if _frontmatter(body).get("name") == skill_id:
                return body
        raise ImportError_(f"Couldn't find SKILL.md for {skill_id} in {source}")

    @staticmethod
    async def _fetch_raw(client: httpx.AsyncClient, source: str, path: str) -> str:
        url = f"{RAW_GITHUB}/{source}/HEAD/{quote(path)}"
        async with client.stream("GET", url) as response:
            _check_response(response)
            body = await _read_capped(response)
        return body.decode("utf-8", errors="replace")

    async def enabled_catalog(
        self, cid: str, user_id: uuid.UUID | None = None, repo: str | None = None
    ) -> tuple[list[SkillRow], list[SkillRow]]:
        enabled = await self._skills.enabled_for_conversation(cid, user_id, repo)
        included: list[SkillRow] = []
        skipped: list[SkillRow] = []
        used = 0
        for skill in enabled:
            cost = len(catalog_line(skill)) + 1
            if used + cost > SKILL_CATALOG_BUDGET_CHARS:
                skipped.append(skill)
                continue
            included.append(skill)
            used += cost
        return included, skipped


def catalog_line(skill: SkillRow) -> str:
    description = " ".join(skill.description.split()) or "no description"
    return f"- {skill.name}: {description}"


def render_skills(skills: list[SkillRow]) -> str:
    return "\n".join(catalog_line(skill) for skill in skills)


class McpService:

    def __init__(
        self, connections: McpConnectionRepository, config: MCPConfig | None = None
    ) -> None:
        self._connections = connections
        self._config = config or MCPConfig()

    @staticmethod
    def target(row: McpConnectionRow) -> mcp_client.McpTarget:
        headers = (
            {row.auth_header: row.auth_value}
            if row.auth_header and row.auth_value
            else {}
        )
        return mcp_client.McpTarget(
            name=row.name,
            server=RemoteMCPServer(url=row.url, headers=headers, transport="http"),
        )

    async def test(self, row: McpConnectionRow) -> tuple[bool, list[str], str | None]:
        try:
            info = await mcp_client.discover(self.target(row))
        except mcp_client.McpError as exc:
            return False, [], str(exc)
        return True, [tool.name for tool in info.tools], None

    async def targets(
        self, cid: str, workspace: Path | None
    ) -> dict[str, mcp_client.McpTarget]:
        rows = await self._connections.enabled_for_conversation(cid)
        targets = {row.id: self.target(row) for row in rows}
        if workspace is not None:
            targets |= mcp_client.config_targets(self._config, workspace)
        return targets
