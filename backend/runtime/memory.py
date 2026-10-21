from __future__ import annotations

import asyncio
import uuid
from typing import Any, Coroutine

from backend.repository.memory import MemoryRepository
from miniagent.tools.memory import REPO_DIR, USER_DIR

DB_TIMEOUT_S = 30


class DbMemoryStore:

    def __init__(
        self,
        repository: MemoryRepository,
        loop: asyncio.AbstractEventLoop,
        user_id: uuid.UUID,
        repo: str | None,
        conversation_id: str,
    ) -> None:
        self._repository = repository
        self._loop = loop
        self._user_id = user_id
        self._repo = repo
        self._conversation_id = conversation_id
        self.has_repo = repo is not None

    def load(self) -> dict[str, str]:
        rows = self._run(self._repository.visible(self._user_id, self._repo))
        return {
            f"{USER_DIR if row.repo is None else REPO_DIR}/{row.path}": row.content
            for row in rows
        }

    def save(self, path: str, content: str) -> None:
        repo, relative = self._split(path)
        self._run(
            self._repository.save(
                user_id=self._user_id,
                repo=repo,
                path=relative,
                content=content,
                conversation_id=self._conversation_id,
            )
        )

    def delete(self, path: str) -> None:
        repo, relative = self._split(path)
        self._run(self._repository.delete(self._user_id, repo, relative))

    def _split(self, path: str) -> tuple[str | None, str]:
        if path.startswith(USER_DIR + "/"):
            return None, path[len(USER_DIR) + 1 :]
        return self._repo, path[len(REPO_DIR) + 1 :]

    def _run(self, coro: Coroutine[Any, Any, Any]) -> Any:
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(DB_TIMEOUT_S)
