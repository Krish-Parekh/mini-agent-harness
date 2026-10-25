from __future__ import annotations

import uuid

import httpx
import pytest
from fastapi import FastAPI

from backend.api.conversations import router
from backend.runtime import changes
from miniagent.events import MessageEvent
from tests.fakes import FakeUserRepository
from tests.test_auth_api import bearer
from tests.test_checkpoints import _git, _rewind_setup, _turn

PNG_V1 = b"\x89PNG\r\n\x1a\n" + bytes(range(256))
PNG_V2 = b"\x89PNG\r\n\x1a\n" + bytes(reversed(range(256)))
WAV = b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00\xff" * 64


@pytest.fixture
async def preview(tmp_path, verifier, user_a, user_b):
    repo, managed, service = _rewind_setup(tmp_path)
    (repo / "logo.png").write_bytes(PNG_V1)
    (repo / "old.png").write_bytes(PNG_V1)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "images")
    managed.user_id = uuid.UUID(user_a.sub)
    managed.branch = None

    async def lookup(cid, user_id):
        return managed if cid == "c1" and user_id == managed.user_id else None

    service.get_or_revive = lookup
    users = FakeUserRepository()
    await users.upsert(user_id=managed.user_id, email=user_a.email, avatar_url=None)
    await users.upsert(user_id=uuid.UUID(user_b.sub), email=user_b.email, avatar_url=None)
    app = FastAPI()
    app.include_router(router)
    app.state.verifier = verifier
    app.state.users = users
    app.state.service = service
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield repo, managed, service, client


async def _get(client, url, **params):
    return await client.get(url, params=params, headers=bearer("token-a"))


async def test_a_file_is_served_as_raw_bytes_with_its_media_type(preview):
    repo, _, _, client = preview
    (repo / "sound.wav").write_bytes(WAV)

    image = await _get(client, "/conversations/c1/files/raw", path="logo.png")
    audio = await _get(client, "/conversations/c1/files/raw", path="sound.wav")

    assert image.status_code == 200
    assert image.headers["content-type"] == "image/png"
    assert image.content == PNG_V1
    assert audio.headers["content-type"].startswith("audio/")
    assert audio.content == WAV


async def test_a_modified_image_has_a_before_and_an_after(preview):
    repo, _, _, client = preview
    (repo / "logo.png").write_bytes(PNG_V2)

    before = await _get(client, "/conversations/c1/changes/raw", path="logo.png", side="before")
    after = await _get(client, "/conversations/c1/changes/raw", path="logo.png", side="after")

    assert before.content == PNG_V1
    assert after.content == PNG_V2
    assert after.headers["content-type"] == "image/png"


async def test_a_deleted_file_keeps_its_before_and_has_no_after(preview):
    repo, _, _, client = preview
    (repo / "old.png").unlink()

    before = await _get(client, "/conversations/c1/changes/raw", path="old.png", side="before")
    after = await _get(client, "/conversations/c1/changes/raw", path="old.png", side="after")

    assert before.content == PNG_V1
    assert after.status_code == 404


async def test_a_turn_scope_compares_that_turns_checkpoints(preview):
    repo, managed, service, client = preview
    await _turn(service, managed, "first", lambda: (repo / "logo.png").write_bytes(PNG_V2))
    await _turn(service, managed, "second", lambda: (repo / "logo.png").write_bytes(WAV))
    first = next(e.id for e in managed.conversation.events if isinstance(e, MessageEvent))

    before = await _get(
        client, "/conversations/c1/changes/raw", path="logo.png", side="before", scope=first
    )
    after = await _get(
        client, "/conversations/c1/changes/raw", path="logo.png", side="after", scope=first
    )

    assert before.content == PNG_V1
    assert after.content == PNG_V2


async def test_files_over_the_cap_are_refused(preview, monkeypatch):
    _, _, _, client = preview
    monkeypatch.setattr(changes, "MAX_PREVIEW_BYTES", len(PNG_V1) - 1)

    current = await _get(client, "/conversations/c1/files/raw", path="logo.png")
    committed = await _get(client, "/conversations/c1/changes/raw", path="logo.png", side="before")

    assert current.status_code == 413
    assert "too large to preview" in current.json()["detail"]
    assert committed.status_code == 413


async def test_paths_outside_the_checkout_and_missing_files_are_not_found(preview):
    _, _, _, client = preview
    for path in ("../repo/logo.png", "/etc/hosts", "missing.png"):
        resp = await _get(client, "/conversations/c1/files/raw", path=path)
        assert resp.status_code == 404


async def test_previews_need_the_owner(preview):
    _, _, _, client = preview
    anonymous = await client.get("/conversations/c1/files/raw", params={"path": "logo.png"})
    other = await client.get(
        "/conversations/c1/files/raw", params={"path": "logo.png"}, headers=bearer("token-b")
    )
    assert anonymous.status_code == 401
    assert other.status_code == 404
