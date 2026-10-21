from __future__ import annotations

import json
import os
import re
from pathlib import Path

import litellm
import pytest

CASSETTES = Path(__file__).parent / "cassettes"
RECORD = os.environ.get("MINIAGENT_RECORD") == "1"
_SECRET_NAME = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|DATABASE_URL")
_SECRET_SHAPE = re.compile(r"sk-[A-Za-z0-9_-]{16,}|sb_secret_[A-Za-z0-9_-]+")


class Cassette:
    def __init__(self, path: Path, real) -> None:
        self.path = path
        self._real = real
        self.entries: list[dict] = [] if RECORD else json.loads(path.read_text())["interactions"]
        self.cursor = 0

    def complete(self, **kwargs):
        roles = [message["role"] for message in kwargs["messages"]]
        if RECORD:
            response = self._real(**kwargs)
            self.entries.append(
                {"model": kwargs["model"], "roles": roles, "response": response.model_dump(mode="json")}
            )
            return response
        assert self.cursor < len(self.entries), f"unrecorded model call #{self.cursor + 1}"
        entry = self.entries[self.cursor]
        self.cursor += 1
        assert entry["roles"] == roles, f"model call #{self.cursor} sent {roles}, recorded {entry['roles']}"
        return litellm.ModelResponse(**entry["response"])

    def save(self) -> None:
        text = json.dumps({"interactions": self.entries}, indent=2)
        secrets = [
            value
            for name, value in os.environ.items()
            if _SECRET_NAME.search(name) and len(value) >= 12
        ]
        if any(secret in text for secret in secrets) or _SECRET_SHAPE.search(text):
            raise AssertionError(f"refusing to write {self.path.name}: it contains a secret")
        self.path.write_text(text + "\n")


@pytest.fixture
def cassette(request, monkeypatch):
    path = CASSETTES / f"{request.node.name}.json"
    if not RECORD and not path.exists():
        pytest.skip(f"no cassette at {path.name}; record with MINIAGENT_RECORD=1")
    if RECORD:
        from dotenv import load_dotenv

        from miniagent.config import Settings, export_provider_keys

        load_dotenv(Path(__file__).parents[1] / ".env")
        export_provider_keys(Settings())
    tape = Cassette(path, litellm.completion)
    monkeypatch.setattr(litellm, "completion", tape.complete)
    yield tape
    if RECORD:
        tape.save()
    else:
        assert tape.cursor == len(tape.entries), (
            f"replay made {tape.cursor} model calls, the cassette has {len(tape.entries)}"
        )
