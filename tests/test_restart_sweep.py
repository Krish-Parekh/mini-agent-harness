from __future__ import annotations

from backend.service.conversation import ConversationService
from tests.test_repository_ownership import repos, sessionmaker  # noqa: F401


async def _conversation(conversations, cid: str, owner, status: str) -> None:
    await conversations.record_event(
        cid=cid,
        user_id=owner,
        repo=None,
        branch=None,
        status=status,
        title=None,
        workspace_dir="/tmp/ws",
        plan=None,
        implementing_plan=False,
        event_id=f"{cid}-e1",
        seq=1,
        source="user",
        kind="message",
        payload={"kind": "message", "role": "user", "text": "hi", "id": f"{cid}-e1"},
    )


async def test_runs_left_running_by_a_restart_are_settled_with_an_error(repos):  # noqa: F811
    conversations, _, a, _ = repos
    await _conversation(conversations, "running1", a, "running")
    await _conversation(conversations, "waiting1", a, "waiting_for_confirmation")
    service = ConversationService(manager=None, repository=conversations, connections=None)

    await service.settle_interrupted_runs()

    settled = await conversations.get("running1", a)
    assert settled.status == "error"
    events = await conversations.list_events("running1")
    assert [e.seq for e in events] == [1, 2]
    assert events[-1].kind == "error"
    assert "server restarted" in events[-1].payload["message"]
    assert (await conversations.get("waiting1", a)).status == "waiting_for_confirmation"
    assert len(await conversations.list_events("waiting1")) == 1
