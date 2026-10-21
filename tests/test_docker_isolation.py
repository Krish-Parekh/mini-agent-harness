from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest

from backend.runtime.manager import ConversationManager
from backend.service import ConversationService
from miniagent.config import Settings
from miniagent.conversation import Status
from miniagent.sandbox.docker import CONVERSATION_LABEL, LABEL
from tests.fakes import FakeConnectionRepository
from tests.test_sandbox_contract import _docker_available

PUBLIC_REPO = "octocat/Hello-World"

docker_only = pytest.mark.skipif(not _docker_available(), reason="docker image not built")


def _settings(tmp_path: Path, **overrides) -> Settings:
    return Settings(
        _env_file=None,
        openai_api_key="unused",
        sandbox_provider="docker",
        workspace_dir=str(tmp_path / "shared-ws"),
        **overrides,
    )


async def test_docker_mounts_only_the_chats_checkout_and_cache_objects(tmp_path) -> None:
    data = tmp_path / "data"
    manager = ConversationManager(_settings(tmp_path), data_dir=data)
    managed = manager.create(user_id=uuid.uuid4(), repo=PUBLIC_REPO, provider="docker")
    cid = managed.conversation.id
    root = data.resolve()
    assert managed.sandbox._mounts == {
        str(root / "worktrees" / cid): "rw",
        str(root / "repos" / "octocat" / "Hello-World" / ".git" / "objects"): "ro",
    }
    assert managed.sandbox.workspace_dir == str(root / "worktrees" / cid)


async def test_repo_less_docker_chat_gets_an_empty_dir_of_its_own(tmp_path) -> None:
    data = tmp_path / "data"
    manager = ConversationManager(_settings(tmp_path), data_dir=data)
    managed = manager.create(user_id=uuid.uuid4(), provider="docker")
    checkout = data.resolve() / "worktrees" / managed.conversation.id
    assert managed.sandbox._mounts == {str(checkout): "rw"}
    assert managed.sandbox.workspace_dir == str(checkout)
    assert checkout.is_dir() and not any(checkout.iterdir())
    manager.release_workspace(managed.conversation.id, None)
    assert not checkout.exists()


async def _bootstrapped(manager: ConversationManager):
    managed = manager.create(user_id=uuid.uuid4(), repo=PUBLIC_REPO, provider="docker")
    await asyncio.to_thread(managed.bootstrap)
    assert managed.conversation.status != Status.ERROR, managed.conversation.events
    return managed


async def _run(managed, command: str):
    return await asyncio.to_thread(managed.sandbox.run_command, command, 60)


@docker_only
async def test_chats_cannot_see_each_other_and_git_works_inside(tmp_path) -> None:
    data = tmp_path / "data"
    manager = ConversationManager(_settings(tmp_path), data_dir=data)
    a = await _bootstrapped(manager)
    b = await _bootstrapped(manager)
    try:
        await asyncio.to_thread(b.sandbox.write_file, "SECRET.md", "b only\n")
        assert (await _run(b, "cat SECRET.md")).stdout == "b only\n"

        assert (await _run(a, f"ls {b.sandbox.workspace_dir}")).exit_code != 0
        cache = data.resolve() / "repos" / "octocat" / "Hello-World"
        assert (await _run(a, f"test -e {cache}/README")).exit_code != 0
        assert (await _run(a, f"test -e {cache}/.git/config")).exit_code != 0
        assert (await _run(a, f"ls {tmp_path / 'shared-ws'}")).exit_code != 0
        objects = cache / ".git" / "objects"
        assert (await _run(a, f"touch {objects}/probe")).exit_code != 0

        origin = await _run(a, "git remote get-url origin")
        assert origin.stdout.strip() == f"https://github.com/{PUBLIC_REPO}.git"
        branch = await _run(a, "git rev-parse --abbrev-ref HEAD")
        assert branch.stdout.strip() == f"miniagent/{a.conversation.id}"
        await asyncio.to_thread(a.sandbox.write_file, "README", "changed\n")
        assert "README" in (await _run(a, "git status --porcelain")).stdout
        assert "+changed" in (await _run(a, "git diff")).stdout
        commit = await _run(
            a, "git -c user.name=t -c user.email=t@example.com commit -qam change && git log -1 --format=%s"
        )
        assert commit.exit_code == 0, commit.stderr
        assert commit.stdout.strip() == "change"
        push = await _run(
            a, "git init -q --bare /tmp/remote.git && git push -q /tmp/remote.git HEAD:refs/heads/out"
        )
        assert push.exit_code == 0, push.stderr
        assert (await _run(a, "git -C /tmp/remote.git fsck --no-progress")).exit_code == 0
        assert (await _run(b, "git status --porcelain")).stdout.strip() == "?? SECRET.md"
    finally:
        for managed in (a, b):
            await asyncio.to_thread(managed.sandbox.close)
            await asyncio.to_thread(manager.release_workspace, managed.conversation.id, PUBLIC_REPO)


@docker_only
async def test_idle_container_stops_and_restarts_with_files_intact(tmp_path) -> None:
    import docker

    manager = ConversationManager(_settings(tmp_path), data_dir=tmp_path / "data")
    managed = manager.create(user_id=uuid.uuid4(), provider="docker")
    client = docker.from_env()
    try:
        await asyncio.to_thread(managed.sandbox.write_file, "notes.txt", "kept\n")
        service = ConversationService(manager, _Repo(set()), FakeConnectionRepository())
        await service.stop_idle_sandboxes(3600)
        assert client.containers.get(managed.sandbox.sandbox_id).status == "running"
        async with managed.lock:
            await service.stop_idle_sandboxes(0)
        assert client.containers.get(managed.sandbox.sandbox_id).status == "running"
        await service.stop_idle_sandboxes(0)
        assert client.containers.get(managed.sandbox.sandbox_id).status == "exited"

        result = await _run(managed, "cat notes.txt")
        assert result.stdout == "kept\n"
        assert client.containers.get(managed.sandbox.sandbox_id).status == "running"
    finally:
        await asyncio.to_thread(managed.sandbox.close)
        client.close()


class _Repo:
    def __init__(self, missing: set[str]) -> None:
        self._missing = missing

    async def existing_ids(self, cids: list[str]) -> set[str]:
        return {cid for cid in cids if cid not in self._missing}


@docker_only
async def test_startup_removes_containers_with_no_conversation(tmp_path) -> None:
    import docker
    import docker.errors

    settings = _settings(tmp_path)
    client = docker.from_env()
    orphan_cid = f"orphan{uuid.uuid4().hex[:6]}"
    orphan = client.containers.run(
        settings.docker_image,
        ["sleep", "infinity"],
        detach=True,
        labels={LABEL: "1", CONVERSATION_LABEL: orphan_cid},
    )
    manager = ConversationManager(settings, data_dir=tmp_path / "data")
    kept = manager.create(user_id=uuid.uuid4(), provider="docker")
    try:
        await asyncio.to_thread(kept.sandbox.run_command, "true")
        service = ConversationService(manager, _Repo({orphan_cid, kept.conversation.id}), FakeConnectionRepository())
        await service.reconcile_sandboxes()
        with pytest.raises(docker.errors.NotFound):
            client.containers.get(orphan.id)
        assert client.containers.get(kept.sandbox.sandbox_id).status == "running"
    finally:
        try:
            orphan.remove(force=True)
        except docker.errors.NotFound:
            pass
        await asyncio.to_thread(kept.sandbox.close)
        client.close()


@docker_only
async def test_destroying_a_never_revived_chat_removes_its_container(tmp_path) -> None:
    import docker
    import docker.errors

    manager = ConversationManager(_settings(tmp_path), data_dir=tmp_path / "data")
    managed = manager.create(user_id=uuid.uuid4(), provider="docker")
    await asyncio.to_thread(managed.sandbox.run_command, "true")
    cid, sandbox_id = managed.conversation.id, managed.sandbox.sandbox_id
    workspace = managed.sandbox.workspace_dir

    restarted = ConversationManager(_settings(tmp_path), data_dir=tmp_path / "data")
    await asyncio.to_thread(restarted.destroy_sandbox, cid, "docker", sandbox_id, workspace)
    client = docker.from_env()
    try:
        with pytest.raises(docker.errors.NotFound):
            client.containers.get(sandbox_id)
    finally:
        client.close()
