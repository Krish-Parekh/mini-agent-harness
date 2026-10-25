from __future__ import annotations

import asyncio

from backend.repository import ConversationRepository
from backend.runtime.manager import ConversationManager
from backend.schemas import StatusUpdate
from backend.service import ConversationService
from miniagent.config import Settings
from miniagent.llm import LLMResponse, ToolCall
from tests.context_snapshot import ScriptedLLM
from tests.fakes import FakeConnectionRepository
from tests.test_repository_ownership import repos, sessionmaker  # noqa: F401
from tests.test_sandbox_failures import SafePolicy


async def test_a_stream_hears_the_run_start_and_end_as_they_happen(
    tmp_path, sessionmaker, repos  # noqa: F811
):
    _, _, owner, _ = repos
    manager = ConversationManager(
        Settings(_env_file=None, sandbox_provider="local"), data_dir=tmp_path / "data"
    )
    service = ConversationService(
        manager, ConversationRepository(sessionmaker), FakeConnectionRepository()
    )
    service.start()
    managed = manager.create(user_id=owner, provider="local", workspace_dir=str(tmp_path / "ws"))
    llm = ScriptedLLM()
    llm.responses.append(
        LLMResponse(tool_calls=[ToolCall(id="c1", name="finish", arguments={"message": "Done."})])
    )
    managed.conversation.agent.llm = llm
    managed.conversation.agent.policy = SafePolicy()
    stream = managed.broker.subscribe()
    try:
        managed.conversation.send_message("hello")
        await asyncio.to_thread(managed.conversation.run)
        await service._persist_queue.join()
        await asyncio.sleep(0)
    finally:
        service._persist_task.cancel()
        for task in service._tasks:
            task.cancel()

    statuses = []
    while not stream.empty():
        item = stream.get_nowait()
        if isinstance(item, StatusUpdate):
            statuses.append(item.status)
    assert statuses == ["running", "finished"]
