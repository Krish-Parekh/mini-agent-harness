from __future__ import annotations

import os
import shutil
import threading
import time
import uuid
from collections.abc import Callable, Iterator

import pytest

from miniagent.sandbox.base import KILLED_EXIT_CODE, TIMEOUT_EXIT_CODE, Sandbox, WorkdirView
from miniagent.sandbox.local import LocalSandbox


def _local(tmp_path, request) -> Sandbox:
    return LocalSandbox(str(tmp_path))


def _docker(tmp_path, request) -> Sandbox:
    from miniagent.sandbox.docker import DockerSandbox

    return DockerSandbox(
        workspace_dir=str(tmp_path),
        image=os.environ.get("MINIAGENT_DOCKER_IMAGE", "miniagent-sandbox:latest"),
        mounts={str(tmp_path): "rw"},
    )


def _docker_available() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        import docker

        client = docker.from_env()
        client.images.get(os.environ.get("MINIAGENT_DOCKER_IMAGE", "miniagent-sandbox:latest"))
        return True
    except Exception:
        return False


def _space_fake(tmp_path, request) -> Sandbox:
    from miniagent.sandbox.space import SpaceConfig, SpaceSandbox
    from tests.space_fake import FakeSpace

    fake = FakeSpace()
    request.addfinalizer(fake.close)
    config = SpaceConfig(
        api_url="http://127.0.0.1:8080",
        data_plane_url="http://127.0.0.1:8090",
        email=fake.email,
        password=fake.password,
    )
    return SpaceSandbox(config, name=f"contract-{uuid.uuid4().hex[:8]}", transport=fake.transport())


def _stubbed(provider: str) -> Callable:
    """The real adapter with its SDK object replaced by a stub that mirrors
    the SDK's call shapes and runs commands in the sandbox image."""

    def build(_tmp_path, request) -> Sandbox:
        from tests import hosted_stubs as stubs

        box = stubs.Container()
        request.addfinalizer(box.remove)
        if provider == "e2b":
            from miniagent.sandbox.e2b import E2BSandbox

            sandbox = E2BSandbox(sandbox_id="stub")
            sandbox._sbx = stubs.E2BStub(box)
        elif provider == "modal":
            from miniagent.sandbox.modal import ModalSandbox

            sandbox = ModalSandbox(sandbox_id="stub")
            sandbox._sb = stubs.ModalStub(box)
        elif provider == "vercel":
            from miniagent.sandbox.vercel import VercelSandbox

            sandbox = VercelSandbox(sandbox_id="stub")
            sandbox._box = stubs.VercelStub(box)
        else:
            from miniagent.sandbox.daytona import DaytonaSandbox

            sandbox = DaytonaSandbox(sandbox_id="stub", workspace_dir="/tmp/workspace")
            sandbox._sbx = stubs.DaytonaStub(box)
        box.run(["mkdir", "-p", sandbox.workspace_dir])
        sandbox._opened = True
        return sandbox

    return build


def _remote(provider: str) -> Callable:
    def build(_tmp_path, _request) -> Sandbox:
        from miniagent.config import Settings
        from miniagent.sandbox.factory import build_sandbox

        return build_sandbox(Settings(sandbox_provider=provider), f"contract-{uuid.uuid4().hex[:8]}")

    return build


_REMOTE_KEYS = {
    "e2b": ["E2B_API_KEY"],
    "daytona": ["DAYTONA_API_KEY"],
    "modal": ["MODAL_TOKEN_ID", "MODAL_TOKEN_SECRET"],
    "vercel": ["VERCEL_TOKEN"],
    "space": ["MINIAGENT_SPACE_API_URL"],
}

_PROVIDERS = [
    pytest.param(_local, id="local"),
    pytest.param(
        _docker,
        id="docker",
        marks=pytest.mark.skipif(not _docker_available(), reason="docker image not built"),
    ),
    pytest.param(
        _space_fake,
        id="space-fake",
        marks=pytest.mark.skipif(not _docker_available(), reason="docker image not built"),
    ),
    *[
        pytest.param(
            _stubbed(name),
            id=f"{name}-stub",
            marks=pytest.mark.skipif(not _docker_available(), reason="docker image not built"),
        )
        for name in ("e2b", "modal", "vercel", "daytona")
    ],
    *[
        pytest.param(
            _remote(name),
            id=name,
            marks=[
                pytest.mark.remote,
                pytest.mark.skipif(
                    not all(os.environ.get(k) for k in keys),
                    reason=f"{name} credentials not set",
                ),
            ],
        )
        for name, keys in _REMOTE_KEYS.items()
    ],
]


@pytest.fixture(params=_PROVIDERS)
def sandbox(request, tmp_path) -> Iterator[Sandbox]:
    box = request.param(tmp_path, request)
    try:
        yield box
    finally:
        box.close()


def test_success_returns_stdout(sandbox: Sandbox) -> None:
    result = sandbox.run_command("echo hello")
    assert result.exit_code == 0
    assert result.stdout.strip() == "hello"


def test_failure_is_returned_not_raised(sandbox: Sandbox) -> None:
    result = sandbox.run_command("echo oops >&2; exit 3")
    assert result.exit_code == 3
    assert "oops" in result.stderr


def test_runs_in_workspace_dir(sandbox: Sandbox) -> None:
    sandbox.write_file("marker.txt", "here")
    assert sandbox.run_command("cat marker.txt").stdout == "here"


def test_env_reaches_command_only(sandbox: Sandbox) -> None:
    secret = f"s-{uuid.uuid4().hex}"
    with_env = sandbox.run_command('printf %s "$MINIAGENT_TEST_SECRET"', env={"MINIAGENT_TEST_SECRET": secret})
    without = sandbox.run_command('printf %s "${MINIAGENT_TEST_SECRET:-}"')
    assert with_env.stdout == secret
    assert without.stdout == ""


def test_timeout_returns_124(sandbox: Sandbox) -> None:
    result = sandbox.run_command("sleep 30", timeout=2)
    assert result.exit_code == TIMEOUT_EXIT_CODE
    assert "timed out" in result.stderr


def test_kill_running_stops_parallel_commands(sandbox: Sandbox) -> None:
    results: list = []

    def run() -> None:
        results.append(sandbox.run_command("sleep 60", timeout=90))

    threads = [threading.Thread(target=run) for _ in range(2)]
    for t in threads:
        t.start()
    time.sleep(3)
    started = time.monotonic()
    sandbox.kill_running()
    for t in threads:
        t.join(timeout=30)
    assert time.monotonic() - started < 15
    assert [r.exit_code for r in results] == [KILLED_EXIT_CODE, KILLED_EXIT_CODE]


def test_kill_running_stops_child_processes(sandbox: Sandbox) -> None:
    done = threading.Event()

    def run() -> None:
        sandbox.run_command("(sleep 45; touch survived) & wait", timeout=90)
        done.set()

    threading.Thread(target=run).start()
    time.sleep(3)
    sandbox.kill_running()
    assert done.wait(30)
    time.sleep(2)
    assert sandbox.run_command("test -e survived").exit_code != 0


def test_file_round_trip(sandbox: Sandbox) -> None:
    content = "line one\nünïcødé ✓\n'quotes' \"double\" $HOME `tick`\n"
    sandbox.write_file("nested/dir/file.txt", content)
    assert sandbox.read_file("nested/dir/file.txt") == content
    assert "file.txt" in sandbox.list_files("nested/dir")
    assert sandbox.list_files("does-not-exist") == []


def test_workdir_scopes_commands_and_files(sandbox: Sandbox) -> None:
    sandbox.write_file("marker.txt", "inner", workdir="sub/dir")
    assert sandbox.read_file("sub/dir/marker.txt") == "inner"
    assert sandbox.read_file("marker.txt", workdir="sub/dir") == "inner"
    assert sandbox.list_files(".", workdir="sub/dir") == ["marker.txt"]
    result = sandbox.run_command("pwd; cat marker.txt", workdir="sub/dir")
    assert result.stdout.splitlines()[0].endswith("/sub/dir")
    assert result.stdout.splitlines()[1] == "inner"


def test_kill_running_reaches_a_workdir_view(sandbox: Sandbox) -> None:
    sandbox.run_command("mkdir -p worker")
    view = WorkdirView(sandbox, "worker")
    view.write_file("only-here.txt", "x")
    assert sandbox.read_file("worker/only-here.txt") == "x"
    results: list = []
    thread = threading.Thread(target=lambda: results.append(view.run_command("sleep 60", timeout=90)))
    thread.start()
    time.sleep(3)
    sandbox.kill_running()
    thread.join(timeout=30)
    assert [r.exit_code for r in results] == [KILLED_EXIT_CODE]
