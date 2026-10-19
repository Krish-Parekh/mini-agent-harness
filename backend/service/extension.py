from __future__ import annotations

import uuid

import httpx
from sqlalchemy.exc import IntegrityError

from backend.models import McpConnectionRow, SkillRow
from backend.repository import McpConnectionRepository, SkillRepository
from backend.runtime import mcp as mcp_client

MAX_SKILL_BYTES = 256 * 1024
IMPORT_TIMEOUT = 10.0
MAX_REDIRECTS = 3
ALLOWED_PREFIXES = ("text/", "application/json")
SKILL_BUDGET_CHARS = 8_000


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


def _name_from_url(url: str) -> str:
    tail = url.rstrip("/").rsplit("/", 1)[-1] or "imported-skill"
    return tail.removesuffix(".md")[:80]


class SkillService:

    def __init__(
        self,
        skills: SkillRepository,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._skills = skills
        self._transport = transport

    async def import_from_url(self, user_id: uuid.UUID, url: str) -> SkillRow:
        if not url.lower().startswith("https://"):
            raise ImportError_("Only https:// URLs can be imported.")

        try:
            async with httpx.AsyncClient(
                timeout=IMPORT_TIMEOUT,
                follow_redirects=True,
                max_redirects=MAX_REDIRECTS,
                transport=self._transport,
            ) as client:
                async with client.stream("GET", url) as response:
                    _check_response(response)
                    body = await _read_capped(response)
        except httpx.HTTPError as exc:
            raise ImportError_(f"Could not fetch the URL: {exc}") from exc

        return await self._save(
            user_id=user_id,
            name=_name_from_url(url),
            description=f"Imported from {url}",
            body=body.decode("utf-8", errors="replace"),
            source_url=url,
        )

    async def create(
        self, user_id: uuid.UUID, name: str, description: str, body: str
    ) -> SkillRow:
        if len(body.encode()) > MAX_SKILL_BYTES:
            raise ImportError_("The skill is larger than 256 KB.")
        return await self._save(
            user_id=user_id, name=name, description=description, body=body
        )

    async def _save(self, **fields) -> SkillRow:
        try:
            return await self._skills.create(**fields)
        except IntegrityError:
            raise ImportError_(
                f"A skill named '{fields['name']}' already exists."
            ) from None

    async def enabled_bodies(self, cid: str) -> tuple[list[SkillRow], list[SkillRow]]:
        enabled = await self._skills.enabled_for_conversation(cid)
        included: list[SkillRow] = []
        skipped: list[SkillRow] = []
        used = 0
        for skill in enabled:
            cost = len(skill.body)
            if used + cost > SKILL_BUDGET_CHARS:
                skipped.append(skill)
                continue
            included.append(skill)
            used += cost
        return included, skipped


def render_skills(skills: list[SkillRow]) -> str:
    if not skills:
        return ""
    blocks = [
        f"## {skill.name}\n{skill.description}\n\n{skill.body}".strip()
        for skill in skills
    ]
    return "\n\n".join(blocks)


class McpService:

    def __init__(self, connections: McpConnectionRepository) -> None:
        self._connections = connections

    @staticmethod
    def target(row: McpConnectionRow) -> mcp_client.McpTarget:
        return mcp_client.McpTarget(
            name=row.name,
            url=row.url,
            auth_header=row.auth_header,
            auth_value=row.auth_value,
        )

    async def test(self, row: McpConnectionRow) -> tuple[bool, list[str], str | None]:
        try:
            tools = await mcp_client.discover(self.target(row))
        except mcp_client.McpError as exc:
            return False, [], str(exc)
        return True, [tool.name for tool in tools], None

    async def enabled(self, cid: str) -> list[McpConnectionRow]:
        return await self._connections.enabled_for_conversation(cid)
