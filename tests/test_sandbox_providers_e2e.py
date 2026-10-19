from __future__ import annotations

import asyncio
import uuid

import httpx
import pytest

from backend.runtime import changes
from backend.runtime.manager import ConversationManager
from miniagent.config import Settings
from miniagent.conversation import Status
from tests.space_fake import FakeSpace
from tests.test_sandbox_contract import _docker_available

pytestmark = pytest.mark.skipif(not _docker_available(), reason="docker image not built")

PUBLIC_REPO = "octocat/Hello-World"


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, openai_api_key="unused", **overrides)


async def _bootstrapped(manager: ConversationManager):
    managed = manager.create(user_id=uuid.uuid4(), repo=PUBLIC_REPO, branch=None, token=None)
    await asyncio.to_thread(managed.bootstrap)
    assert managed.conversation.status != Status.ERROR, managed.conversation.events
    return managed


async def test_docker_runs_in_a_host_worktree_mounted_at_the_same_path(tmp_path) -> None:
    settings = _settings(sandbox_provider="docker", workspace_dir=str(tmp_path / "ws"))
    manager = ConversationManager(settings, data_dir=tmp_path / "data")
    managed = await _bootstrapped(manager)
    cid = managed.conversation.id
    box = managed.sandbox
    try:
        assert box.workspace_dir.startswith(str((tmp_path / "data").resolve()))
        branch = await asyncio.to_thread(box.run_command, "git rev-parse --abbrev-ref HEAD")
        assert branch.stdout.strip() == f"miniagent/{cid}"
        assert (await asyncio.to_thread(box.run_command, "cat /etc/os-release")).stdout.count("bookworm")
        await asyncio.to_thread(box.write_file, "NEW.md", "hello\n")
        files = await asyncio.to_thread(changes.list_changes, box)
        assert [f.path for f in files] == ["NEW.md"]
    finally:
        await asyncio.to_thread(box.close)
        await asyncio.to_thread(manager.release_workspace, cid, PUBLIC_REPO)


@pytest.fixture
def fake_space(monkeypatch):
    fake = FakeSpace()
    real_client = httpx.Client

    def client(**kwargs):
        return real_client(**{**kwargs, "transport": fake.transport()})

    monkeypatch.setattr("miniagent.sandbox.space.httpx.Client", client)
    yield fake
    fake.close()


async def test_space_clones_inside_the_sandbox_and_survives_a_restart(tmp_path, fake_space) -> None:
    settings = _settings(
        sandbox_provider="space",
        space_api_url="http://127.0.0.1:8080",
        space_data_plane_url="http://127.0.0.1:8090",
        space_token=fake_space.token,
    )
    manager = ConversationManager(settings, data_dir=tmp_path / "data")
    managed = await _bootstrapped(manager)
    cid = managed.conversation.id
    sandbox_id = managed.sandbox.sandbox_id
    assert sandbox_id in fake_space.sandboxes
    assert not (tmp_path / "data" / "worktrees" / cid).exists()

    branch = await asyncio.to_thread(managed.sandbox.run_command, "git rev-parse --abbrev-ref HEAD")
    assert branch.stdout.strip() == f"miniagent/{cid}"
    origin = await asyncio.to_thread(managed.sandbox.run_command, "git remote get-url origin")
    assert origin.stdout.strip() == f"https://github.com/{PUBLIC_REPO}.git"
    await asyncio.to_thread(managed.sandbox.write_file, "NEW.md", "hello\n")

    restarted = ConversationManager(settings, data_dir=tmp_path / "data")
    revived = restarted.register_revived(
        cid=cid,
        user_id=managed.user_id,
        repo=PUBLIC_REPO,
        branch=None,
        workspace_dir=managed.sandbox.workspace_dir,
        status="idle",
        title=None,
        events=[],
        sandbox_provider="space",
        sandbox_id=sandbox_id,
    )
    files = await asyncio.to_thread(changes.list_changes, revived.sandbox)
    assert [f.path for f in files] == ["NEW.md"]

    await asyncio.to_thread(restarted.destroy_sandbox, cid, "space", sandbox_id, revived.sandbox.workspace_dir)
    assert sandbox_id not in fake_space.sandboxes
