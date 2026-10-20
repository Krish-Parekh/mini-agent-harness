from __future__ import annotations

import html
import re
from concurrent.futures import ThreadPoolExecutor

import httpx
from pydantic import BaseModel

REGISTRY_URL = "https://skills.sh"
SEARCH_TIMEOUT = 10.0
DESCRIPTION_TIMEOUT = 5.0
DEFAULT_LIMIT = 8

_META_TAG = re.compile(r"<meta\b[^>]*\bname=\"description\"[^>]*>", re.IGNORECASE)
_CONTENT = re.compile(r"\bcontent=\"([^\"]*)\"", re.IGNORECASE)


class RegistryError(Exception):
    pass


class SkillHit(BaseModel):
    id: str
    source: str
    skill_id: str
    name: str
    installs: int = 0
    description: str = ""


def page_url(registry_id: str) -> str:
    return f"{REGISTRY_URL}/{registry_id}"


def _description(page: str) -> str:
    tag = _META_TAG.search(page)
    if tag is None:
        return ""
    content = _CONTENT.search(tag.group(0))
    return html.unescape(content.group(1)).strip() if content else ""


def _fetch_description(client: httpx.Client, registry_id: str) -> str:
    try:
        response = client.get(page_url(registry_id), timeout=DESCRIPTION_TIMEOUT)
    except httpx.HTTPError:
        return ""
    if response.status_code >= 400:
        return ""
    return _description(response.text)


def search(
    query: str,
    limit: int = DEFAULT_LIMIT,
    transport: httpx.BaseTransport | None = None,
) -> list[SkillHit]:
    with httpx.Client(
        follow_redirects=True, timeout=SEARCH_TIMEOUT, transport=transport
    ) as client:
        try:
            response = client.get(f"{REGISTRY_URL}/api/search", params={"q": query})
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise RegistryError(f"skills.sh search failed: {exc}") from exc
        hits = [
            SkillHit(
                id=item.get("id") or f"{item['source']}/{item['skillId']}",
                source=item["source"],
                skill_id=item["skillId"],
                name=item.get("name") or item["skillId"],
                installs=int(item.get("installs") or 0),
            )
            for item in payload.get("skills") or []
            if item.get("source") and item.get("skillId")
        ][:limit]
        if not hits:
            return []
        with ThreadPoolExecutor(max_workers=len(hits)) as pool:
            descriptions = pool.map(
                lambda hit: _fetch_description(client, hit.id), hits
            )
            return [
                hit.model_copy(update={"description": description})
                for hit, description in zip(hits, descriptions)
            ]
