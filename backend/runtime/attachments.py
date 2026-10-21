from __future__ import annotations

import posixpath
import shlex
from typing import Any

import httpx

from miniagent.agent import SPILL_ROOT, exclude_from_git
from miniagent.events import Attachment
from miniagent.sandbox.base import Sandbox

BUCKET = "attachments"
LINK_TTL_S = 7 * 24 * 3600
MAX_ATTACHMENTS = 10
MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_IMAGE_BYTES = 5 * 1024 * 1024
IMAGE_MIMES = ("image/png", "image/jpeg", "image/webp", "image/gif")
ATTACHMENTS_DIR = f"{SPILL_ROOT}/attachments"


class AttachmentError(Exception):
    pass


class Storage:

    def __init__(self, url: str, key: str) -> None:
        self._url = url.rstrip("/")
        self._key = key

    async def sign(self, token: str, paths: list[str]) -> dict[str, str]:
        items = await self._request(
            "POST",
            f"/object/sign/{BUCKET}",
            token,
            {"expiresIn": LINK_TTL_S, "paths": paths},
        )
        signed = {item["path"]: item.get("signedURL") for item in items}
        missing = [path for path in paths if not signed.get(path)]
        if missing:
            raise AttachmentError(f"attachment not found: {missing[0]}")
        return {path: f"{self._url}/storage/v1{signed[path]}" for path in paths}

    async def delete(self, token: str, paths: list[str]) -> None:
        await self._request("DELETE", f"/object/{BUCKET}", token, {"prefixes": paths})

    async def _request(self, method: str, path: str, token: str, body: dict) -> Any:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.request(
                    method,
                    f"{self._url}/storage/v1{path}",
                    headers={"apikey": self._key, "Authorization": f"Bearer {token}"},
                    json=body,
                )
        except httpx.HTTPError as exc:
            raise AttachmentError(f"storage unreachable: {exc}") from exc
        if response.status_code != 200:
            raise AttachmentError(f"storage returned {response.status_code}")
        return response.json()


def copy_into_sandbox(sandbox: Sandbox, attachments: list[Attachment]) -> None:
    exclude_from_git(sandbox)
    for attachment in attachments:
        result = sandbox.run_command(
            f"mkdir -p {shlex.quote(posixpath.dirname(attachment.workspace_path))} && "
            f"curl -fsSL --max-filesize {MAX_FILE_BYTES} --max-time 60 "
            f"-o {shlex.quote(attachment.workspace_path)} {shlex.quote(attachment.url or '')}",
            timeout=90,
        )
        if result.exit_code != 0:
            raise AttachmentError(
                f"could not copy {attachment.name} into the sandbox "
                f"(exit {result.exit_code}): "
                f"{(result.stderr.strip() or result.stdout.strip())[:200]}"
            )
