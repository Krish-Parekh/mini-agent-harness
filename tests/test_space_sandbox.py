from __future__ import annotations

import json

import httpx
import pytest

from miniagent.sandbox.base import TIMEOUT_EXIT_CODE, SandboxError, SandboxExpired
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


def _creates(fake: FakeSpace) -> list[httpx.Request]:
    return [r for r in fake.requests if r.method == "POST" and r.url.path == "/v1/sandboxes"]


def test_plain_http_is_rejected_off_loopback() -> None:
    with pytest.raises(ValueError, match="https"):
        SpaceSandbox(SpaceConfig(api_url="http://space.example.com", data_plane_url=DATA))


def test_client_ignores_environment_proxies(fake: FakeSpace) -> None:
    box = _box(fake)
    assert box._http._trust_env is False
    assert box._http.follow_redirects is False


@needs_docker
def test_create_sends_template_policy_and_idempotency_key(fake: FakeSpace) -> None:
    box = _box(fake, name="cid123")
    try:
        box.ensure_open()
        (create,) = _creates(fake)
        body = json.loads(create.content)
        assert create.headers["Idempotency-Key"] == "miniagent-create-cid123"
        assert body["template"] == "code-runtime:latest"
        assert body["network_policy"]["egress"]["default_action"] == "allow"
        assert body["network_policy"]["tls_interception"] == "off"
        assert box.sandbox_id.startswith("sbx_")
    finally:
        box.close()


@needs_docker
def test_network_policy_can_be_left_to_the_operator(fake: FakeSpace) -> None:
    box = _box(fake, name="cid124", config={"allow_internet": False})
    try:
        box.ensure_open()
        assert "network_policy" not in json.loads(_creates(fake)[0].content)
    finally:
        box.close()


@needs_docker
def test_retried_create_reuses_the_same_sandbox(fake: FakeSpace) -> None:
    first = _box(fake, name="same")
    second = _box(fake, name="same")
    first.ensure_open()
    second.ensure_open()
    assert first.sandbox_id == second.sandbox_id
    assert len(fake.sandboxes) == 1
    first.close()


@needs_docker
def test_expired_token_logs_in_again(fake: FakeSpace) -> None:
    box = _box(fake, name="relogin")
    try:
        box.ensure_open()
        fake.reject_next_token = True
        assert box.run_command("echo ok").stdout.strip() == "ok"
        logins = [r for r in fake.requests if r.url.path == "/auth/v1/sessions"]
        assert len(logins) == 2
    finally:
        box.close()


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


@needs_docker
def test_close_deletes_and_polls(fake: FakeSpace) -> None:
    box = _box(fake, name="bye")
    box.ensure_open()
    sandbox_id = box.sandbox_id
    box.close()
    assert sandbox_id not in fake.sandboxes
    delete = next(r for r in fake.requests if r.method == "DELETE")
    assert delete.headers["Idempotency-Key"]


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


def test_server_timeout_maps_to_124() -> None:
    box = _stream_box([{"type": "process_exited", "exit_code": -1, "status": "timed_out"}])
    assert box.run_command("sleep 100", timeout=1).exit_code == TIMEOUT_EXIT_CODE


def test_stream_without_exit_is_an_error() -> None:
    box = _stream_box([{"type": "attached"}])
    with pytest.raises(SandboxError, match="without process_exited"):
        box.run_command("true")


def test_lost_output_is_an_error() -> None:
    box = _stream_box([{"type": "resync_required", "reason": "lag"}])
    with pytest.raises(SandboxError, match="resync_required"):
        box.run_command("true")


def test_foreign_events_url_is_refused() -> None:
    box = _stream_box([], events_url="https://evil.example.com/v1/sessions/proc_1/events")
    with pytest.raises(SandboxError, match="unexpected events URL"):
        box.run_command("true")
