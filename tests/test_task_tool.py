from __future__ import annotations

import subprocess
import threading
import time
from types import SimpleNamespace

import pytest
from pydantic import TypeAdapter

from backend.service.conversation import ConversationService
from miniagent.agent import Agent
from miniagent.confirm import ConfirmPolicy
from miniagent.conversation import Conversation, Status
from miniagent.events import (
    Events,
    LLMUsageEvent,
    ObservationEvent,
    WorkerEvent,
    WorkerStatusEvent,
)
from miniagent.factory import headless_tools
from miniagent.llm import LLMResponse, TokenUsage, ToolCall
from miniagent.policy import CommandPolicy
from miniagent.sandbox.base import Sandbox
from miniagent.sandbox.local import LocalSandbox
from miniagent.tools.base import ToolRegistry
from miniagent.tools.task import TaskTool
from tests.test_repository_ownership import repos, sessionmaker  # noqa: F401
from tests.test_sandbox_contract import _docker, _docker_available


class RoutedLLM:
    model = "scripted"

    def __init__(self, parent: list[LLMResponse], workers: dict[str, list[LLMResponse]]) -> None:
        self.scripts = {"": parent, **workers}
        self._lock = threading.Lock()

    def context_window(self) -> int:
        return 1_000_000

    def count_tokens(self, messages, tools=None) -> int:
        return 0

    def complete(self, messages, tools=None, phase="agent"):
        if phase == "finish_nudge":
            return LLMResponse()
        said = " ".join(
            m["content"] for m in messages if m["role"] == "user" and isinstance(m["content"], str)
        )
        key = next((k for k in self.scripts if k and k in said), "")
        with self._lock:
            return self.scripts[key].pop(0)


class WritePolicy:
    def classify_bash(self, command: str) -> CommandPolicy:
        return CommandPolicy(risk="safe", read_only=">" not in command, is_verification=False)

    def classify_finish_message(self, message: str) -> CommandPolicy:
        return CommandPolicy(risk="safe", read_only=True)


def call(id: str, name: str, **arguments) -> LLMResponse:
    return LLMResponse(tool_calls=[ToolCall(id=id, name=name, arguments=arguments)])


def task(*tasks: dict) -> LLMResponse:
    return call("task_1", "task", tasks=list(tasks))


def git(cwd, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.rstrip("\n")


@pytest.fixture(
    params=[
        "local",
        pytest.param(
            "docker",
            marks=pytest.mark.skipif(not _docker_available(), reason="docker image not built"),
        ),
    ]
)
def sandbox(request, tmp_path):
    box = LocalSandbox(str(tmp_path)) if request.param == "local" else _docker(tmp_path, request)
    yield box
    box.close()


def repo(path) -> None:
    git(path, "init", "-q", "-b", "main")
    (path / "notes.txt").write_text("one\ntwo\nthree\n")
    git(path, "add", ".")
    git(path, "commit", "-q", "-m", "init")
    git(path, "checkout", "-q", "-b", "miniagent/c1")


def parent(sandbox: Sandbox, llm: RoutedLLM) -> Conversation:
    agent = Agent(
        llm=llm,
        tools=ToolRegistry([*headless_tools(), TaskTool(headless_tools)]),
        policy=WritePolicy(),
    )
    return Conversation(
        agent=agent,
        sandbox=sandbox,
        confirm_policy=ConfirmPolicy("never"),
        id="c1",
        stuck_detection=False,
    )


def statuses(conversation: Conversation) -> dict[str, WorkerStatusEvent]:
    return {
        e.title: e for e in conversation.events if isinstance(e, WorkerStatusEvent)
    }


def worker_observations(conversation: Conversation, worker_id: str) -> list[ObservationEvent]:
    return [
        e.event
        for e in conversation.events
        if isinstance(e, WorkerEvent)
        and e.worker_id == worker_id
        and isinstance(e.event, ObservationEvent)
    ]


def test_forks_see_uncommitted_work_and_both_merge_back(tmp_path, sandbox):
    repo(tmp_path)
    head = git(tmp_path, "rev-parse", "HEAD")
    (tmp_path / "notes.txt").write_text("one\ntwo\nthree\nparent edit\n")
    (tmp_path / "draft.txt").write_text("parent draft\n")
    llm = RoutedLLM(
        [
            task(
                {"kind": "fork", "title": "Alpha", "prompt": "FORK-A: write alpha.txt"},
                {"kind": "fork", "title": "Beta", "prompt": "FORK-B: write beta.txt"},
            ),
            call("p2", "finish", message="Both forks merged."),
        ],
        {
            "FORK-A": [
                call("a1", "file_edit", command="view", path="notes.txt"),
                call("a2", "file_edit", command="create", path="alpha.txt", content="alpha\n"),
                call("a3", "finish", message="Wrote alpha.txt"),
            ],
            "FORK-B": [
                call("b1", "file_edit", command="view", path="draft.txt"),
                call("b2", "file_edit", command="create", path="beta.txt", content="beta\n"),
                call("b3", "finish", message="Wrote beta.txt"),
            ],
        },
    )
    conversation = parent(sandbox, llm)
    conversation.send_message("Split the work.")
    conversation.run()

    assert conversation.status == Status.FINISHED
    alpha, beta = statuses(conversation)["Alpha"], statuses(conversation)["Beta"]
    assert (alpha.status, alpha.merged, alpha.files, alpha.report) == ("done", True, ["alpha.txt"], "Wrote alpha.txt")
    assert (beta.status, beta.merged, beta.files) == ("done", True, ["beta.txt"])
    [seen_notes, _, _] = worker_observations(conversation, alpha.worker_id)
    [seen_draft, _, _] = worker_observations(conversation, beta.worker_id)
    assert "parent edit" in seen_notes.content
    assert seen_draft.content == "parent draft\n"

    assert (tmp_path / "alpha.txt").read_text() == "alpha\n"
    assert (tmp_path / "beta.txt").read_text() == "beta\n"
    assert (tmp_path / "notes.txt").read_text().endswith("parent edit\n")
    assert git(tmp_path, "rev-parse", "HEAD") == head
    assert git(tmp_path, "status", "--porcelain").splitlines() == [
        " M notes.txt",
        "?? alpha.txt",
        "?? beta.txt",
        "?? draft.txt",
    ]
    assert len(git(tmp_path, "worktree", "list").splitlines()) == 1
    assert git(tmp_path, "diff", "--name-only", alpha.base, alpha.branch) == "alpha.txt"

    managed = SimpleNamespace(repo="octo/app", sandbox=sandbox, conversation=conversation)
    service = ConversationService(manager=None, repository=None, connections=None)
    assert [f.path for f in service.list_changes(managed, beta.worker_id)] == ["beta.txt"]
    assert "+beta" in service.file_diff(managed, "beta.txt", beta.worker_id).patch

    [observation] = [
        e for e in conversation.events if isinstance(e, ObservationEvent) and e.tool_name == "task"
    ]
    assert [w["merged"] for w in observation.details["workers"]] == [True, True]


def test_a_fork_that_conflicts_keeps_its_branch_and_leaves_the_workspace_clean(tmp_path, sandbox):
    repo(tmp_path)

    def rewrite(prefix: str, line: str) -> list[LLMResponse]:
        return [
            call(f"{prefix}1", "file_edit", command="view", path="notes.txt"),
            call(f"{prefix}2", "file_edit", command="str_replace", path="notes.txt", old_str="two", new_str=line),
            call(f"{prefix}3", "finish", message=f"Set line two to {line}"),
        ]

    llm = RoutedLLM(
        [
            task(
                {"kind": "fork", "title": "First", "prompt": "FORK-A: reword line two"},
                {"kind": "fork", "title": "Second", "prompt": "FORK-B: reword line two"},
            ),
            call("p2", "finish", message="One fork conflicted."),
        ],
        {"FORK-A": rewrite("a", "TWO-A"), "FORK-B": rewrite("b", "TWO-B")},
    )
    conversation = parent(sandbox, llm)
    conversation.send_message("Reword line two twice.")
    conversation.run()

    first, second = statuses(conversation)["First"], statuses(conversation)["Second"]
    assert first.merged and first.conflict is None
    assert not second.merged
    assert "CONFLICT" in second.conflict
    assert (tmp_path / "notes.txt").read_text() == "one\nTWO-A\nthree\n"
    assert not (tmp_path / ".git" / "MERGE_HEAD").exists()
    assert git(tmp_path, "show", f"{second.branch}:notes.txt") == "one\nTWO-B\nthree"
    assert not (tmp_path / ".miniagent" / "workers" / second.worker_id).exists()


def test_an_explore_worker_cannot_write(tmp_path):
    repo(tmp_path)
    llm = RoutedLLM(
        [
            task({"kind": "explore", "title": "Look", "prompt": "EXPLORE: look around"}),
            call("p2", "finish", message="Explored."),
        ],
        {
            "EXPLORE": [
                call("e1", "file_edit", command="create", path="hack.txt", content="x"),
                call("e2", "bash", command="echo x > hack.txt"),
                call("e3", "finish", message="notes.txt has three lines"),
            ]
        },
    )
    conversation = parent(LocalSandbox(str(tmp_path)), llm)
    conversation.send_message("Look around.")
    conversation.run()

    look = statuses(conversation)["Look"]
    edit, shell, _ = worker_observations(conversation, look.worker_id)
    assert edit.error and "read-only" in edit.content
    assert shell.error and "read-only" in shell.content
    assert not (tmp_path / "hack.txt").exists()
    assert (look.status, look.report) == ("done", "notes.txt has three lines")


def test_stop_ends_every_worker_loop(tmp_path):
    repo(tmp_path)
    sandbox = LocalSandbox(str(tmp_path))
    llm = RoutedLLM(
        [
            task(
                {"kind": "explore", "title": "Wait", "prompt": "EXPLORE: wait"},
                {"kind": "fork", "title": "Busy", "prompt": "FORK-A: wait"},
            ),
            call("p2", "finish", message="never reached"),
        ],
        {
            "EXPLORE": [call("e1", "bash", command="sleep 60"), call("e2", "bash", command="ls")],
            "FORK-A": [call("a1", "bash", command="sleep 60"), call("a2", "bash", command="ls")],
        },
    )
    conversation = parent(sandbox, llm)
    conversation.send_message("Wait.")

    def stop() -> None:
        time.sleep(3)
        conversation.request_cancel()
        sandbox.kill_running()

    threading.Thread(target=stop).start()
    started = time.monotonic()
    conversation.run()

    assert time.monotonic() - started < 20
    assert conversation.status == Status.IDLE
    assert {t: s.status for t, s in statuses(conversation).items()} == {"Wait": "cancelled", "Busy": "cancelled"}
    assert [len(script) for script in llm.scripts.values()] == [1, 1, 1]
    assert not statuses(conversation)["Busy"].merged
    assert len(git(tmp_path, "worktree", "list").splitlines()) == 1


async def test_worker_events_replay_after_a_restart(tmp_path, repos):  # noqa: F811
    conversations, _, owner, _ = repos
    repo(tmp_path)
    llm = RoutedLLM(
        [
            task({"kind": "explore", "title": "Look", "prompt": "EXPLORE: look"}),
            call("p2", "finish", message="Done."),
        ],
        {
            "EXPLORE": [
                LLMResponse(
                    tool_calls=[ToolCall(id="e1", name="finish", arguments={"message": "Found it."})],
                    usage=TokenUsage(prompt_tokens=10, completion_tokens=2, total_tokens=12),
                )
            ]
        },
    )
    conversation = parent(LocalSandbox(str(tmp_path)), llm)
    conversation.send_message("Look.")
    conversation.run()
    for seq, event in enumerate(conversation.events, start=1):
        await conversations.record_event(
            cid="c1",
            user_id=owner,
            repo=None,
            branch=None,
            status="finished",
            title=None,
            workspace_dir=str(tmp_path),
            plan=None,
            implementing_plan=False,
            event_id=event.id,
            seq=seq,
            source=event.source,
            kind=event.kind,
            payload=event.model_dump(),
        )

    adapter = TypeAdapter(Events)
    replayed = [adapter.validate_python(row.payload) for row in await conversations.list_events("c1")]

    assert replayed == conversation.events
    wrapped = [e.event for e in replayed if isinstance(e, WorkerEvent)]
    assert any(isinstance(e, LLMUsageEvent) and e.total_tokens == 12 for e in wrapped)
    assert [e.status for e in replayed if isinstance(e, WorkerStatusEvent)] == ["running", "done"]
