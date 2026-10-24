from __future__ import annotations

import asyncio
import uuid

from backend.runtime.manager import ConversationManager
from backend.schemas import StatusUpdate
from miniagent.config import Settings
from miniagent.llm import LLMResponse, ToolCall
from tests.context_snapshot import ScriptedLLM
from tests.test_sandbox_failures import SafePolicy


async def test_a_stream_hears_the_run_start_and_end_as_they_happen(tmp_path):
    manager = ConversationManager(
        Settings(_env_file=None, sandbox_provider="local"), data_dir=tmp_path / "data"
    )
    managed = manager.create(
        user_id=uuid.uuid4(), provider="local", workspace_dir=str(tmp_path / "ws")
    )
    llm = ScriptedLLM()
    llm.responses.append(
        LLMResponse(tool_calls=[ToolCall(id="c1", name="finish", arguments={"message": "Done."})])
    )
    managed.conversation.agent.llm = llm
    managed.conversation.agent.policy = SafePolicy()
    stream = managed.broker.subscribe()

    managed.conversation.send_message("hello")
    await asyncio.to_thread(managed.conversation.run)
    await asyncio.sleep(0)

    statuses = []
    while not stream.empty():
        item = stream.get_nowait()
        if isinstance(item, StatusUpdate):
            statuses.append(item.status)
    assert statuses == ["running", "finished"]
