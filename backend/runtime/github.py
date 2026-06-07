from __future__ import annotations

import secrets


class GitHubAuth:
    """Single-user, in-memory GitHub connection for v1. The token lives only in
    process memory and is never written to an event or persisted."""

    def __init__(self) -> None:
        self.token: str | None = None
        self.login: str | None = None
        self._pending_states: set[str] = set()

    def new_state(self) -> str:
        state = secrets.token_urlsafe(16)
        self._pending_states.add(state)
        return state

    def consume_state(self, state: str) -> bool:
        return state in self._pending_states and (
            self._pending_states.discard(state) or True
        )
