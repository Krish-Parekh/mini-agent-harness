from __future__ import annotations

import asyncio
import subprocess
from types import SimpleNamespace

import pytest

from backend.runtime import changes, checkpoints
from backend.runtime.checkpoints import CheckpointError
from backend.service.conversation import ConversationService
from miniagent.conversation import Conversation, Status
from miniagent.events import MessageEvent
from miniagent.agent import exclude_from_git
from miniagent.sandbox.local import LocalSandbox


def _git(cwd, *args) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "app.py").write_text("v1\n")
    (repo / "notes.txt").write_text("keep\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    (repo / "draft.md").write_text("untracked before the turn\n")
    return repo


def test_restore_puts_the_checkout_back_and_keeps_the_branch(tmp_path):
    repo = _repo(tmp_path)
    sandbox = LocalSandbox(str(repo))
    (repo / ".miniagent" / "attachments").mkdir(parents=True)
    (repo / ".miniagent" / "attachments" / "shot.png").write_text("png")
    exclude_from_git(sandbox)
    head = _git(repo, "rev-parse", "HEAD")
    checkpoints.record(sandbox, "m1")

    (repo / "app.py").write_text("v2\n")
    (repo / "notes.txt").unlink()
    (repo / "new.py").write_text("created by the agent\n")

    checkpoints.restore(sandbox, "m1")

    assert (repo / "app.py").read_text() == "v1\n"
    assert (repo / "notes.txt").read_text() == "keep\n"
    assert (repo / "draft.md").read_text() == "untracked before the turn\n"
    assert not (repo / "new.py").exists()
    assert (repo / ".miniagent" / "attachments" / "shot.png").exists()
    assert _git(repo, "rev-parse", "HEAD") == head
    assert _git(repo, "status", "--porcelain") == "?? draft.md"


def test_record_never_moves_the_branch_and_is_idempotent(tmp_path):
    repo = _repo(tmp_path)
    sandbox = LocalSandbox(str(repo))
    head = _git(repo, "rev-parse", "HEAD")
    checkpoints.record(sandbox, "m1")
    first = _git(repo, "rev-parse", checkpoints.ref("m1"))
    (repo / "app.py").write_text("v2\n")
    checkpoints.record(sandbox, "m1")

    assert _git(repo, "rev-parse", checkpoints.ref("m1")) == first
    assert _git(repo, "rev-parse", "HEAD") == head
    assert _git(repo, "log", "--format=%H", "main") == head
    assert checkpoints.exists(sandbox, "m1")


def test_dropped_checkpoints_are_gone(tmp_path):
    sandbox = LocalSandbox(str(_repo(tmp_path)))
    checkpoints.record(sandbox, "m1")
    checkpoints.record(sandbox, "m2")
    checkpoints.drop(sandbox, ["m1", "m2"])
    assert not checkpoints.exists(sandbox, "m1")
    assert not checkpoints.exists(sandbox, "m2")


def _rewind_setup(tmp_path):
    repo = _repo(tmp_path)
    sandbox = LocalSandbox(str(repo))
    exclude_from_git(sandbox)
    conversation = Conversation(agent=SimpleNamespace(), sandbox=sandbox, stuck_detection=False)
    managed = SimpleNamespace(
        conversation=conversation, sandbox=sandbox, repo="octo/repo", lock=asyncio.Lock()
    )
    service = ConversationService(SimpleNamespace(), None, None)

    async def persisted(*_):
        return None

    service._persist_status = persisted
    return repo, managed, service


async def _turn(service, managed, text, edit):
    managed.conversation.send_message(text)
    await service._checkpoint(managed, managed.conversation.events[-1].id)
    edit()
    managed.conversation.add_event(MessageEvent(role="assistant", text=f"did {text}"))


async def test_rewinding_restores_files_and_hides_the_later_turns(tmp_path):
    repo, managed, service = _rewind_setup(tmp_path)
    conv = managed.conversation
    await _turn(service, managed, "first", lambda: (repo / "app.py").write_text("v2\n"))
    first = conv.events[0]
    await _turn(service, managed, "second", lambda: (repo / "extra.py").write_text("x\n"))

    message = await service.rewind(managed, first.id)

    assert message.text == "first"
    assert (repo / "app.py").read_text() == "v1\n"
    assert not (repo / "extra.py").exists()
    assert [e for e in conv.live_events() if isinstance(e, MessageEvent)] == []
    assert first.id in conv.compacted_event_ids()
    assert not checkpoints.exists(managed.sandbox, first.id)
    assert len(conv.events) == 5


async def test_rewinding_to_a_later_turn_keeps_the_earlier_one(tmp_path):
    repo, managed, service = _rewind_setup(tmp_path)
    conv = managed.conversation
    await _turn(service, managed, "first", lambda: (repo / "app.py").write_text("v2\n"))
    await _turn(service, managed, "second", lambda: (repo / "app.py").write_text("v3\n"))
    second = [e for e in conv.events if isinstance(e, MessageEvent) and e.text == "second"][0]

    await service.rewind(managed, second.id)

    assert (repo / "app.py").read_text() == "v2\n"
    assert [e.text for e in conv.live_events() if isinstance(e, MessageEvent)] == [
        "first",
        "did first",
    ]
    assert checkpoints.exists(managed.sandbox, conv.events[0].id)


async def test_rewinding_is_refused_while_a_run_is_active(tmp_path):
    _, managed, service = _rewind_setup(tmp_path)
    managed.conversation.send_message("first")
    managed.conversation.status = Status.RUNNING
    with pytest.raises(CheckpointError, match="stop the current run"):
        await service.rewind(managed, managed.conversation.events[0].id)


async def test_each_turn_shows_only_its_own_changes(tmp_path):
    repo, managed, service = _rewind_setup(tmp_path)
    managed.branch = None
    conv = managed.conversation
    await _turn(service, managed, "first", lambda: (repo / "app.py").write_text("v2\n"))
    await _turn(service, managed, "second", lambda: (repo / "extra.py").write_text("x\n"))
    first, second = [e.id for e in conv.events if isinstance(e, MessageEvent) and e.role == "user"]

    assert [(f.path, f.status) for f in service.list_changes(managed, first)] == [("app.py", "modified")]
    assert [(f.path, f.status) for f in service.list_changes(managed, second)] == [("extra.py", "added")]
    assert {f.path for f in service.list_changes(managed, "all")} == {"app.py", "draft.md", "extra.py"}
    assert [t.text for t in service.turns(managed)] == ["first", "second"]
    assert "+v2" in service.file_diff(managed, "app.py", first).patch


async def test_a_turn_without_a_checkpoint_is_refused(tmp_path):
    _, managed, service = _rewind_setup(tmp_path)
    managed.conversation.send_message("no checkpoint")
    with pytest.raises(CheckpointError):
        service.list_changes(managed, managed.conversation.events[0].id)


def test_large_patches_are_capped(tmp_path):
    repo = _repo(tmp_path)
    (repo / "app.py").write_text("x" * (changes.MAX_PATCH_CHARS + 10) + "\n")
    diff = changes.file_diff(LocalSandbox(str(repo)), "app.py")
    assert diff.truncated
    assert len(diff.patch) == changes.MAX_PATCH_CHARS
