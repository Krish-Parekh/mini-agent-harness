from __future__ import annotations

import json

import httpx
import pytest

from miniagent.sandbox.base import SandboxError, SandboxExpired
from miniagent.sandbox.space import SpaceConfig, SpaceSandbox
from tests.space_fake import FakeSpace
from tests.test_sandbox_contract import _docker_available

needs_docker = pytest.mark.skipif(not _docker_available(), reason="docker image not built")

API = "http://127.0.0.1:8080"
DATA = "http://127.0.0.1:8090"


@pytest.fixture
def fake():
    space = FakeSpace()
    yield space
    space.close()


def _box(fake: FakeSpace, **overrides) -> SpaceSandbox:
    config = SpaceConfig(
        api_url=API, data_plane_url=DATA, email=fake.email, password=fake.password,
        **overrides.pop("config", {}),
    )
    return SpaceSandbox(config, transport=fake.transport(), **overrides)


def test_plain_http_is_rejected_off_loopback() -> None:
    with pytest.raises(ValueError, match="https"):
        SpaceSandbox(SpaceConfig(api_url="http://space.example.com", data_plane_url=DATA))


@needs_docker
def test_retried_create_reuses_the_same_sandbox(fake: FakeSpace) -> None:
    first = _box(fake, name="same")
    second = _box(fake, name="same")
    first.ensure_open()
    second.ensure_open()
    assert first.sandbox_id == second.sandbox_id
    assert len(fake.sandboxes) == 1
    first.close()


def test_reconnect_to_missing_sandbox_is_expired(fake: FakeSpace) -> None:
    box = _box(fake, sandbox_id="sbx_gone")
    with pytest.raises(SandboxExpired):
        box.run_command("true")


@needs_docker
def test_reconnect_wakes_a_suspended_sandbox(fake: FakeSpace) -> None:
    box = _box(fake, name="sleepy")
    box.ensure_open()
    fake.sandboxes[box.sandbox_id].state = "suspended"
    revived = _box(fake, sandbox_id=box.sandbox_id)
    try:
        assert revived.run_command("echo awake").stdout.strip() == "awake"
        assert any(r.url.path.endswith(":wake") for r in fake.requests)
    finally:
        revived.close()


def _stream_box(frames: list[dict], events_url: str = "/v1/sessions/proc_1/events") -> SpaceSandbox:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/sandboxes/sbx_1/commands":
            return httpx.Response(201, json={
                "session_id": "proc_1",
                "attach": {"events_url": events_url, "token": "attach"},
            })
        if request.url.path == "/v1/sessions/proc_1/events":
            payload = "".join(f"data: {json.dumps(f)}\n\n" for f in frames)
            return httpx.Response(200, content=payload.encode())
        return httpx.Response(404)

    box = SpaceSandbox(
        SpaceConfig(api_url=API, data_plane_url=DATA, token="t"),
        sandbox_id="sbx_1",
        transport=httpx.MockTransport(handle),
    )
    box._opened = True
    return box


def test_foreign_events_url_is_refused() -> None:
    box = _stream_box([], events_url="https://evil.example.com/v1/sessions/proc_1/events")
    with pytest.raises(SandboxError, match="unexpected events URL"):
        box.run_command("true")
