from __future__ import annotations

import asyncio
import uuid

import pytest

from backend.repository import MemoryRepository, UserRepository
from backend.runtime.memory import DbMemoryStore
from miniagent.agent import Agent
from miniagent.confirm import ConfirmPolicy
from miniagent.conversation import Conversation
from miniagent.events import MemoryIndexEvent
from miniagent.llm import LLMResponse, ToolCall
from miniagent.sandbox.local import LocalSandbox
from miniagent.tools.base import ToolRegistry
from miniagent.tools.finish import FinishTool
from miniagent.tools.memory import MAX_MEMORY_CHARS, MemoryAction, MemoryTool, memory_index
from tests.test_agent_history import QueueLLM
from tests.test_repository_ownership import sessionmaker  # noqa: F401
from tests.test_sandbox_failures import SafePolicy


class FakeStore:
    def __init__(self, files: dict[str, str] | None = None, has_repo: bool = True) -> None:
        self.files = dict(files or {})
        self.has_repo = has_repo

    def load(self) -> dict[str, str]:
        return dict(self.files)

    def save(self, path: str, content: str) -> None:
        self.files[path] = content

    def delete(self, path: str) -> None:
        del self.files[path]


def _run(store: FakeStore, **kwargs):
    return MemoryTool(store).execute(MemoryAction(**kwargs), sandbox=None)


def test_viewing_an_empty_store_lists_both_scopes():
    result = _run(FakeStore(), command="view", path="/memories")
    assert not result.error
    assert result.output.splitlines()[1:] == [
        "0.0K\t/memories",
        "0.0K\t/memories/repo",
        "0.0K\t/memories/user",
    ]


def test_create_then_view_shows_numbered_lines():
    store = FakeStore()
    created = _run(store, command="create", path="/memories/user/style.md", file_text="Short answers\nNo emoji\n")
    assert created.output == "File created successfully at: /memories/user/style.md"
    viewed = _run(store, command="view", path="/memories/user/style.md", view_range=[2, -1])
    assert viewed.output == (
        "Here's the content of /memories/user/style.md with line numbers:\n     2\tNo emoji"
    )


def test_str_replace_needs_a_unique_match():
    store = FakeStore({"/memories/repo/test.md": "run make\nrun make\n"})
    duplicate = _run(store, command="str_replace", path="/memories/repo/test.md", old_str="run make", new_str="x")
    assert duplicate.error and "in lines: [1, 2]" in duplicate.output
    missing = _run(store, command="str_replace", path="/memories/repo/test.md", old_str="pytest", new_str="x")
    assert missing.error and "did not appear verbatim" in missing.output
    edited = _run(store, command="str_replace", path="/memories/repo/test.md", old_str="run make\nrun", new_str="run make check\nskip")
    assert edited.output == "The memory file has been edited."
    assert store.files["/memories/repo/test.md"] == "run make check\nskip make\n"


def test_insert_delete_and_rename():
    store = FakeStore({"/memories/repo/notes/a.md": "one\ntwo"})
    _run(store, command="insert", path="/memories/repo/notes/a.md", insert_line=0, insert_text="zero\n")
    assert store.files["/memories/repo/notes/a.md"] == "zero\none\ntwo"
    renamed = _run(store, command="rename", old_path="/memories/repo/notes", new_path="/memories/user/notes")
    assert renamed.output == "Successfully renamed /memories/repo/notes to /memories/user/notes"
    assert list(store.files) == ["/memories/user/notes/a.md"]
    deleted = _run(store, command="delete", path="/memories/user/notes")
    assert deleted.output == "Successfully deleted /memories/user/notes"
    assert store.files == {}


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"command": "view", "path": "/memories/../etc/passwd"}, "is outside /memories"),
        ({"command": "create", "path": "/memories/top.md", "file_text": "x"}, "live under"),
        ({"command": "delete", "path": "/memories/user"}, "cannot be deleted"),
        ({"command": "view", "path": "/memories/user/nope.md"}, "does not exist"),
        ({"command": "create", "path": "/memories/user/big.md", "file_text": "x" * (MAX_MEMORY_CHARS + 1)}, "limited to"),
    ],
)
def test_bad_requests_are_refused(kwargs, message):
    result = _run(FakeStore(), **kwargs)
    assert result.error and message in result.output


def test_repo_scope_is_unavailable_without_a_repository():
    result = _run(FakeStore(has_repo=False), command="create", path="/memories/repo/x.md", file_text="x")
    assert result.error and "no repository" in result.output


def test_index_lists_each_memory_by_its_first_line():
    index = memory_index(
        {"/memories/user/style.md": "\nShort answers\nWhy: busy", "/memories/repo/test.md": "make check"}
    )
    assert index == "/memories/repo/test.md: make check\n/memories/user/style.md: Short answers"
    assert memory_index({}) == "No memories saved yet."


def test_the_index_is_added_once_and_reaches_the_model(tmp_path):
    store = FakeStore({"/memories/user/style.md": "No comments in code"})
    save = ToolCall(
        id="call_save",
        name="memory",
        arguments={"command": "create", "path": "/memories/repo/test.md", "file_text": "make check"},
    )
    llm = QueueLLM(LLMResponse(tool_calls=[save]), LLMResponse(text="saved"), LLMResponse(text="ok"))
    agent = Agent(
        llm=llm,
        tools=ToolRegistry([MemoryTool(store), FinishTool()]),
        policy=SafePolicy(),
        memory=store,
    )
    conversation = Conversation(
        agent=agent,
        sandbox=LocalSandbox(str(tmp_path)),
        confirm_policy=ConfirmPolicy("never"),
        stuck_detection=False,
    )
    conversation.send_message("remember the test command")
    conversation.run()
    conversation.send_message("again")
    conversation.run()

    [index] = [e for e in conversation.events if isinstance(e, MemoryIndexEvent)]
    assert index.content == "/memories/user/style.md: No comments in code"
    assert any("No comments in code" in str(m["content"]) for m in llm.seen[0])
    assert store.files["/memories/repo/test.md"] == "make check"


async def test_db_store_keeps_scopes_apart(sessionmaker):  # noqa: F811
    users = UserRepository(sessionmaker)
    user = await users.upsert(user_id=uuid.uuid4(), email="m@x.com", avatar_url=None)
    repository = MemoryRepository(sessionmaker)
    loop = asyncio.get_running_loop()
    web = DbMemoryStore(repository, loop, user.id, "octo/web", "c1")
    api = DbMemoryStore(repository, loop, user.id, "octo/api", "c2")

    await asyncio.to_thread(web.save, "/memories/user/style.md", "Long answers")
    await asyncio.to_thread(api.save, "/memories/user/style.md", "Short answers")
    await asyncio.to_thread(web.save, "/memories/repo/test.md", "npm test")
    await asyncio.to_thread(web.save, "/memories/repo/test.md", "npm run test")
    await asyncio.to_thread(api.save, "/memories/repo/test.md", "pytest")

    assert await asyncio.to_thread(web.load) == {
        "/memories/user/style.md": "Short answers",
        "/memories/repo/test.md": "npm run test",
    }
    assert await asyncio.to_thread(api.load) == {
        "/memories/user/style.md": "Short answers",
        "/memories/repo/test.md": "pytest",
    }
    await asyncio.to_thread(api.delete, "/memories/user/style.md")
    assert await asyncio.to_thread(web.load) == {"/memories/repo/test.md": "npm run test"}
