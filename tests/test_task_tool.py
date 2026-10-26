from __future__ import annotations

import asyncio
import subprocess
import threading
import time
from collections.abc import Callable
from types import SimpleNamespace

import pytest
from pydantic import TypeAdapter

from backend.repository import ConversationRepository
from backend.runtime.manager import ConversationManager
from backend.service.conversation import ConversationService
from miniagent.config import Settings
from miniagent.agent import Agent
from miniagent.confirm import ConfirmPolicy
from miniagent.conversation import Conversation, Status
from miniagent.events import (
    ActionEvent,
    Events,
    LLMUsageEvent,
    ObservationEvent,
    WorkerEvent,
    WorkerResultEvent,
    WorkerStatusEvent,
)
from miniagent.factory import core_tools
from miniagent.llm import LLMResponse, TokenUsage, ToolCall
from miniagent.policy import CommandPolicy
from miniagent.sandbox.base import Sandbox
from miniagent.sandbox.local import LocalSandbox
from miniagent.tools.base import ToolRegistry
from miniagent.tools.task import TaskTool
from tests.fakes import FakeConnectionRepository
from tests.test_repository_ownership import repos, sessionmaker  # noqa: F401
from tests.test_sandbox_contract import _docker, _docker_available

Scripted = LLMResponse | Callable[[], LLMResponse]


class RoutedLLM:
    """Scripted LLM routed by a key in the user messages. The parent ("") says
    "noted" once its script is used up: background results arrive in an order
    and batching the test cannot fix, and each one may start a parent turn."""

    model = "scripted"

    def __init__(self, parent: list[Scripted], workers: dict[str, list[Scripted]]) -> None:
        self.scripts = {"": parent, **workers}
        self.seen: dict[str, list[list[dict]]] = {key: [] for key in self.scripts}
        self.nudges = 0
        self._lock = threading.Lock()

    def context_window(self) -> int:
        return 1_000_000

    def count_tokens(self, messages, tools=None) -> int:
        return 0

    def complete(self, messages, tools=None, phase="agent", tool_choice="auto"):
        if phase == "finish_nudge":
            self.nudges += 1
            return LLMResponse()
        said = " ".join(
            m["content"] for m in messages if m["role"] == "user" and isinstance(m["content"], str)
        )
        key = next((k for k in self.scripts if k and k in said), "")
        with self._lock:
            self.seen[key].append(messages)
            if not key and not self.scripts[key]:
                return LLMResponse(text="noted")
            item = self.scripts[key].pop(0)
        return item() if callable(item) else item


class WritePolicy:
    def classify_bash(self, command: str) -> CommandPolicy:
        return CommandPolicy(risk="safe", read_only=">" not in command, is_verification=False)

    def classify_finish_message(self, message: str) -> CommandPolicy:
        return CommandPolicy(risk="safe", read_only=True)


def call(id: str, name: str, **arguments) -> LLMResponse:
    return LLMResponse(tool_calls=[ToolCall(id=id, name=name, arguments=arguments)])


def task(*tasks: dict, id: str = "task_1") -> LLMResponse:
    return call(id, "task", tasks=list(tasks))


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


def parent(
    sandbox: Sandbox, llm: RoutedLLM, mode: str = "full", explore_iterations: int = 50
) -> Conversation:
    agent = Agent(
        llm=llm,
        tools=ToolRegistry(
            [*core_tools(), TaskTool(core_tools, explore_iterations=explore_iterations)]
        ),
        policy=WritePolicy(),
    )
    return Conversation(
        agent=agent,
        sandbox=sandbox,
        confirm_policy=ConfirmPolicy(mode),
        id="c1",
        stuck_detection=False,
    )


def statuses(conversation: Conversation) -> dict[str, WorkerStatusEvent]:
    return {
        e.title: e for e in conversation.events if isinstance(e, WorkerStatusEvent)
    }


def results(conversation: Conversation) -> dict[str, WorkerResultEvent]:
    return {e.title: e for e in conversation.events if isinstance(e, WorkerResultEvent)}


def worker_observations(conversation: Conversation, worker_id: str) -> list[ObservationEvent]:
    return [
        e.event
        for e in conversation.events
        if isinstance(e, WorkerEvent)
        and e.worker_id == worker_id
        and isinstance(e.event, ObservationEvent)
    ]


def task_observation(conversation: Conversation, call_id: str = "task_1") -> ObservationEvent:
    return next(
        e
        for e in conversation.events
        if isinstance(e, ObservationEvent) and e.tool_call_id == call_id
    )


def parent_saw(llm: RoutedLLM, text: str) -> bool:
    return any(
        isinstance(m["content"], str) and text in m["content"]
        for messages in llm.seen[""]
        for m in messages
    )


def test_task_returns_at_once_and_results_arrive_as_messages(tmp_path):
    repo(tmp_path)
    release = threading.Event()

    def slow_finish() -> LLMResponse:
        release.wait(10)
        return call("e1", "finish", message="notes.txt has three lines")

    llm = RoutedLLM(
        [
            task({"kind": "explore", "title": "Look", "prompt": "EXPLORE: count lines"}),
            LLMResponse(text="Waiting for the worker."),
        ],
        {"EXPLORE": [slow_finish]},
    )
    conversation = parent(LocalSandbox(str(tmp_path)), llm)
    conversation.send_message("Count the lines.")
    conversation.run()

    assert conversation.status == Status.IDLE
    assert conversation.workers.live() == 1
    assert llm.nudges == 0
    assert "Started 1 worker(s) in the background" in task_observation(conversation).content
    release.set()
    assert conversation.workers.wait(10)
    conversation.run_until_settled()

    look = results(conversation)["Look"]
    assert (look.status, look.report) == ("done", "notes.txt has three lines")
    assert parent_saw(llm, "[worker result] Look (explore")
    assert parent_saw(llm, "notes.txt has three lines")


def test_a_worker_that_hits_its_step_limit_still_reports(tmp_path):
    repo(tmp_path)
    llm = RoutedLLM(
        [task({"kind": "explore", "title": "Review", "prompt": "EXPLORE: review"})],
        {
            "EXPLORE": [
                call("e1", "terminal", command="ls"),
                call("e2", "terminal", command="cat notes.txt"),
                LLMResponse(text="Partial review: notes.txt looks fine; did not check tests."),
            ]
        },
    )
    conversation = parent(LocalSandbox(str(tmp_path)), llm, explore_iterations=2)
    conversation.send_message("Review.")
    conversation.run_until_settled()

    review = results(conversation)["Review"]
    assert (review.status, review.stop_reason) == ("partial", "step_limit")
    assert review.report == "Partial review: notes.txt looks fine; did not check tests."
    assert parent_saw(llm, "partial: it stopped at its step limit")
    assert parent_saw(llm, "did not check tests")


def test_a_worker_that_replies_without_finish_still_reports(tmp_path):
    repo(tmp_path)
    llm = RoutedLLM(
        [task({"kind": "explore", "title": "Ask", "prompt": "EXPLORE: answer"})],
        {"EXPLORE": [LLMResponse(text="The answer is three.")]},
    )
    conversation = parent(LocalSandbox(str(tmp_path)), llm)
    conversation.send_message("Answer.")
    conversation.run_until_settled()

    answer = results(conversation)["Ask"]
    assert (answer.status, answer.stop_reason, answer.report) == (
        "partial",
        "no_finish",
        "The answer is three.",
    )


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
    conversation.run_until_settled()

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
    assert git(tmp_path, "diff", "--cached", "--name-only") == ""
    assert git(tmp_path, "status", "--porcelain").splitlines() == [
        " M notes.txt",
        "?? alpha.txt",
        "?? beta.txt",
        "?? draft.txt",
    ]
    assert len(git(tmp_path, "worktree", "list").splitlines()) == 1
    assert git(tmp_path, "diff", "--name-only", alpha.base, alpha.branch) == "alpha.txt"
    assert parent_saw(llm, "Merged into the workspace: alpha.txt.")

    managed = SimpleNamespace(repo="octo/app", sandbox=sandbox, conversation=conversation)
    service = ConversationService(manager=None, repository=None, connections=None)
    assert [f.path for f in service.list_changes(managed, beta.worker_id)] == ["beta.txt"]
    assert "+beta" in service.file_diff(managed, "beta.txt", beta.worker_id).patch

    first_call = llm.seen["FORK-A"][0]
    brief = next(
        m["content"] for m in reversed(first_call) if m["content"] == "FORK-A: write alpha.txt"
    )
    assert "<worker-fork>" not in brief
    assert "<worker-fork>" in first_call[-1]["content"]
    assert f"worktree at `{tmp_path}/.miniagent/workers/{alpha.worker_id}`" in first_call[-1]["content"]


def test_parent_edits_made_while_a_fork_runs_survive_the_merge(tmp_path):
    repo(tmp_path)
    head = git(tmp_path, "rev-parse", "HEAD")
    edited = threading.Event()

    def after_parent_edit() -> LLMResponse:
        edited.wait(10)
        return call("a1", "file_edit", command="view", path="notes.txt")

    llm = RoutedLLM(
        [
            task({"kind": "fork", "title": "Top", "prompt": "FORK-A: capitalise line one"}),
            call("p1", "file_edit", command="view", path="notes.txt"),
            call("p2", "file_edit", command="str_replace", path="notes.txt", old_str="three", new_str="THREE"),
            lambda: (edited.set(), LLMResponse(text="Fork is running."))[1],
        ],
        {
            "FORK-A": [
                after_parent_edit,
                call("a2", "file_edit", command="str_replace", path="notes.txt", old_str="one", new_str="ONE"),
                call("a3", "finish", message="Capitalised line one"),
            ]
        },
    )
    conversation = parent(LocalSandbox(str(tmp_path)), llm)
    conversation.send_message("Capitalise two lines.")
    conversation.run_until_settled()

    top = results(conversation)["Top"]
    assert top.merged and top.conflict is None
    assert (tmp_path / "notes.txt").read_text() == "ONE\ntwo\nTHREE\n"
    assert git(tmp_path, "rev-parse", "HEAD") == head
    assert git(tmp_path, "rev-parse", "--abbrev-ref", "HEAD") == "miniagent/c1"
    assert git(tmp_path, "diff", "--cached", "--name-only") == ""


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
        ],
        {"FORK-A": rewrite("a", "TWO-A"), "FORK-B": rewrite("b", "TWO-B")},
    )
    conversation = parent(sandbox, llm)
    conversation.send_message("Reword line two twice.")
    conversation.run_until_settled()

    ended = results(conversation)
    [merged] = [r for r in ended.values() if r.merged]
    [conflicted] = [r for r in ended.values() if not r.merged]
    assert merged.conflict is None
    assert conflicted.conflict == "Conflicting files: notes.txt"
    line = "TWO-A" if merged.title == "First" else "TWO-B"
    other = "TWO-B" if line == "TWO-A" else "TWO-A"
    assert (tmp_path / "notes.txt").read_text() == f"one\n{line}\nthree\n"
    assert not (tmp_path / ".git" / "MERGE_HEAD").exists()
    assert git(tmp_path, "show", f"{conflicted.branch}:notes.txt") == f"one\n{other}\nthree"
    assert not (tmp_path / ".miniagent" / "workers" / conflicted.worker_id).exists()


def test_a_fork_cannot_write_into_the_parent_checkout(tmp_path):
    repo(tmp_path)
    llm = RoutedLLM(
        [task({"kind": "fork", "title": "Escape", "prompt": "FORK-A: edit notes"})],
        {
            "FORK-A": [
                call("a1", "file_edit", command="create", path=str(tmp_path / "escaped.txt"), content="x"),
                call("a2", "file_edit", command="create", path="../../escaped.txt", content="x"),
                call("a3", "finish", message="Could not write outside the worktree"),
            ]
        },
    )
    conversation = parent(LocalSandbox(str(tmp_path)), llm)
    conversation.send_message("Edit.")
    conversation.run_until_settled()

    escape = statuses(conversation)["Escape"]
    absolute, relative, _ = worker_observations(conversation, escape.worker_id)
    assert absolute.error and "outside this worker's directory" in absolute.content
    assert relative.error and "outside this worker's directory" in relative.content
    assert not (tmp_path / "escaped.txt").exists()
    assert escape.files == []


def test_workers_in_ask_mode_are_refused_instead_of_waiting_for_approval(tmp_path):
    repo(tmp_path)
    llm = RoutedLLM(
        [task({"kind": "fork", "title": "Write", "prompt": "FORK-A: write a file"})],
        {
            "FORK-A": [
                call("a1", "file_edit", command="create", path="new.txt", content="x"),
                call("a2", "finish", message="Writing needs approval"),
            ]
        },
    )
    conversation = parent(LocalSandbox(str(tmp_path)), llm, mode="ask")
    conversation.send_message("Write.")
    conversation.run_until_settled()

    write = results(conversation)["Write"]
    [refused, _] = worker_observations(conversation, write.worker_id)
    assert refused.error and "needs the user's approval" in refused.content
    assert (write.status, write.report) == ("done", "Writing needs approval")
    assert not (tmp_path / "new.txt").exists()


def test_plan_mode_refuses_forks_but_allows_explore_workers(tmp_path):
    repo(tmp_path)
    llm = RoutedLLM(
        [
            task({"kind": "fork", "title": "Change", "prompt": "FORK-A: change"}),
            task({"kind": "explore", "title": "Read", "prompt": "EXPLORE: read"}, id="task_2"),
        ],
        {
            "FORK-A": [],
            "EXPLORE": [call("e1", "finish", message="read it")],
        },
    )
    conversation = parent(LocalSandbox(str(tmp_path)), llm)
    conversation.send_message("Plan a change.", plan_mode=True)
    conversation.run_until_settled()

    refused = task_observation(conversation)
    assert refused.error and "Plan mode is on" in refused.content
    assert "Change" not in statuses(conversation)
    assert results(conversation)["Read"].status == "done"


def test_typed_input_cannot_bypass_a_read_only_worker(tmp_path):
    repo(tmp_path)
    llm = RoutedLLM(
        [task({"kind": "explore", "title": "Look", "prompt": "EXPLORE: look around"})],
        {
            "EXPLORE": [
                call("e1", "file_edit", command="create", path="hack.txt", content="x"),
                call("e2", "terminal", command="echo x > hack.txt"),
                call("e3", "terminal", command="echo x > hack.txt", is_input=True),
                call("e4", "finish", message="notes.txt has three lines"),
            ]
        },
    )
    conversation = parent(LocalSandbox(str(tmp_path)), llm)
    conversation.send_message("Look around.")
    conversation.run_until_settled()

    look = statuses(conversation)["Look"]
    edit, shell, typed, _ = worker_observations(conversation, look.worker_id)
    assert edit.error and "read-only" in edit.content
    assert shell.error and "read-only" in shell.content
    assert typed.error and "read-only" in typed.content
    assert not (tmp_path / "hack.txt").exists()
    assert (look.status, look.report) == ("done", "notes.txt has three lines")


def test_forks_use_the_parents_dependencies_without_committing_them(tmp_path):
    repo(tmp_path)
    (tmp_path / ".gitignore").write_text("node_modules/\n")
    git(tmp_path, "add", ".gitignore")
    git(tmp_path, "commit", "-q", "-m", "ignore")
    (tmp_path / "node_modules" / "pkg").mkdir(parents=True)
    (tmp_path / "node_modules" / "pkg" / "index.js").write_text("module.exports = 42\n")
    llm = RoutedLLM(
        [task({"kind": "fork", "title": "Use", "prompt": "FORK-A: use the package"})],
        {
            "FORK-A": [
                call("a1", "file_edit", command="view", path="node_modules/pkg/index.js"),
                call("a2", "file_edit", command="create", path="answer.txt", content="42\n"),
                call("a3", "finish", message="The package exports 42"),
            ]
        },
    )
    conversation = parent(LocalSandbox(str(tmp_path)), llm)
    conversation.send_message("Use the package.")
    conversation.run_until_settled()

    use = results(conversation)["Use"]
    [seen, _, _] = worker_observations(conversation, use.worker_id)
    assert "module.exports = 42" in seen.content
    assert (use.merged, use.files) == (True, ["answer.txt"])
    assert "node_modules" not in git(tmp_path, "ls-tree", "-r", "--name-only", use.branch)
    assert (tmp_path / "node_modules" / "pkg" / "index.js").read_text() == "module.exports = 42\n"
    assert not (tmp_path / "node_modules").is_symlink()


def test_no_more_than_ten_workers_run_at_once(tmp_path):
    repo(tmp_path)
    release = threading.Event()

    def held() -> LLMResponse:
        release.wait(10)
        return call("h1", "finish", message="held")

    hold = [{"kind": "explore", "title": f"Hold {i}", "prompt": "HOLD: wait"} for i in range(8)]
    more = [{"kind": "explore", "title": f"More {i}", "prompt": "HOLD: wait"} for i in range(3)]
    llm = RoutedLLM(
        [
            task(*hold),
            task(*more, id="task_2"),
            lambda: (release.set(), LLMResponse(text="Waiting."))[1],
        ],
        {"HOLD": [held] * 8},
    )
    conversation = parent(LocalSandbox(str(tmp_path)), llm)
    conversation.send_message("Hold.")
    conversation.run_until_settled()

    refused = task_observation(conversation, "task_2")
    assert refused.error and "At most 10 workers can run at once; 8 are running" in refused.content
    assert len(results(conversation)) == 8
    assert all(r.status == "done" for r in results(conversation).values())


def test_a_stopped_worker_can_be_resumed_with_its_history(tmp_path):
    repo(tmp_path)
    conversation: Conversation

    def resume() -> LLMResponse:
        worker_id = results(conversation)["Review"].worker_id
        return task({"resume": worker_id, "prompt": "RESUME: finish the review"}, id="task_2")

    llm = RoutedLLM(
        [
            task({"kind": "explore", "title": "Review", "prompt": "EXPLORE: review"}),
            LLMResponse(text="Waiting."),
            resume,
        ],
        {
            "RESUME": [call("r1", "finish", message="Review complete: tests are fine too.")],
            "EXPLORE": [
                call("e1", "terminal", command="ls"),
                call("e2", "terminal", command="ls"),
                LLMResponse(text="Partial: checked the files, not the tests."),
            ],
        },
    )
    conversation = parent(LocalSandbox(str(tmp_path)), llm, explore_iterations=2)
    conversation.send_message("Review.")
    conversation.run_until_settled()

    ended = [e for e in conversation.events if isinstance(e, WorkerResultEvent)]
    assert [(e.status, e.stop_reason) for e in ended] == [("partial", "step_limit"), ("done", None)]
    assert ended[0].worker_id == ended[1].worker_id
    assert ended[1].report == "Review complete: tests are fine too."
    resumed_call = llm.seen["RESUME"][0]
    said = [m["content"] for m in resumed_call if m["role"] == "user" and isinstance(m["content"], str)]
    assert "EXPLORE: review" in said and "RESUME: finish the review" in said


def test_stop_ends_every_background_worker(tmp_path):
    repo(tmp_path)
    sandbox = LocalSandbox(str(tmp_path))
    llm = RoutedLLM(
        [
            task(
                {"kind": "explore", "title": "Wait", "prompt": "EXPLORE: wait"},
                {"kind": "fork", "title": "Busy", "prompt": "FORK-A: wait"},
            ),
            LLMResponse(text="Waiting."),
        ],
        {
            "EXPLORE": [call("e1", "terminal", command="sleep 60"), call("e2", "terminal", command="ls")],
            "FORK-A": [call("a1", "terminal", command="sleep 60"), call("a2", "terminal", command="ls")],
        },
    )
    conversation = parent(sandbox, llm)
    conversation.send_message("Wait.")
    conversation.run()
    assert conversation.workers.live() == 2

    def sleeping() -> int:
        return sum(
            isinstance(e, WorkerEvent) and isinstance(e.event, ActionEvent)
            for e in list(conversation.events)
        )

    deadline = time.monotonic() + 20
    while sleeping() < 2 and time.monotonic() < deadline:
        time.sleep(0.05)
    time.sleep(1)
    started = time.monotonic()
    conversation.request_cancel()
    sandbox.kill_running()
    while conversation.workers.wait(20) and conversation.workers.live():
        time.sleep(0.1)

    assert time.monotonic() - started < 20
    assert {t: s.status for t, s in statuses(conversation).items()} == {"Wait": "cancelled", "Busy": "cancelled"}
    assert [len(llm.scripts[k]) for k in ("EXPLORE", "FORK-A")] == [1, 1]
    assert len(git(tmp_path, "worktree", "list").splitlines()) == 1


async def test_worker_events_replay_after_a_restart(tmp_path, repos):  # noqa: F811
    conversations, _, owner, _ = repos
    repo(tmp_path)
    llm = RoutedLLM(
        [task({"kind": "explore", "title": "Look", "prompt": "EXPLORE: look"})],
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
    conversation.run_until_settled()
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
            plan_mode=False,
            permission_mode="auto",
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
    assert [e.report for e in replayed if isinstance(e, WorkerResultEvent)] == ["Found it."]


async def _drain(service) -> None:
    await asyncio.sleep(0)
    await service._persist_queue.join()
    service._persist_task.cancel()
    for pending in list(service._tasks):
        pending.cancel()


async def test_an_idle_parent_wakes_up_when_a_background_worker_finishes(
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
    release = threading.Event()

    def slow_finish() -> LLMResponse:
        release.wait(10)
        return call("e1", "finish", message="Found the config in settings.py")

    llm = RoutedLLM(
        [
            task({"kind": "explore", "title": "Find", "prompt": "EXPLORE: find the config"}),
            LLMResponse(text="Waiting for the worker."),
        ],
        {"EXPLORE": [slow_finish]},
    )
    managed.conversation.agent.llm = llm
    managed.conversation.agent.policy = WritePolicy()
    try:
        await service.send_message(managed, "Find the config.")
        for _ in range(100):
            if managed.conversation.status == Status.IDLE and not managed.lock.locked():
                break
            await asyncio.sleep(0.05)
        assert managed.conversation.status == Status.IDLE
        assert not results(managed.conversation)

        release.set()
        for _ in range(200):
            if parent_saw(llm, "Found the config in settings.py") and not managed.lock.locked():
                break
            await asyncio.sleep(0.05)
    finally:
        await _drain(service)

    assert parent_saw(llm, "[worker result] Find (explore")
    assert managed.conversation.status == Status.IDLE
    assert managed.conversation.events[-1].text == "noted"


async def test_reopening_a_chat_settles_workers_a_restart_left_running(
    tmp_path, sessionmaker, repos  # noqa: F811
):
    conversations, _, owner, _ = repos
    repo(tmp_path)
    release = threading.Event()
    llm = RoutedLLM(
        [task({"kind": "explore", "title": "Long", "prompt": "EXPLORE: long job"})],
        {
            "EXPLORE": [
                LLMResponse(
                    text="Halfway: read the README.",
                    tool_calls=[ToolCall(id="e1", name="terminal", arguments={"command": "ls"})],
                ),
                lambda: (release.wait(10), call("e2", "finish", message="x"))[1],
            ]
        },
    )
    crashed = parent(LocalSandbox(str(tmp_path)), llm)
    crashed.send_message("Run the long job.")
    crashed.run()
    for _ in range(100):
        if any(isinstance(e, WorkerEvent) and isinstance(e.event, ObservationEvent) for e in crashed.events):
            break
        time.sleep(0.05)
    for seq, event in enumerate(list(crashed.events), start=1):
        await conversations.record_event(
            cid="c1",
            user_id=owner,
            repo=None,
            branch=None,
            status="idle",
            title=None,
            workspace_dir=str(tmp_path),
            plan=None,
            implementing_plan=False,
            plan_mode=False,
            permission_mode="auto",
            event_id=event.id,
            seq=seq,
            source=event.source,
            kind=event.kind,
            payload=event.model_dump(),
        )
    release.set()

    manager = ConversationManager(
        Settings(_env_file=None, sandbox_provider="local"), data_dir=tmp_path / "data"
    )
    service = ConversationService(manager, conversations, FakeConnectionRepository())
    service.start()
    try:
        opened = await asyncio.gather(*(service.get_or_revive("c1", owner) for _ in range(3)))
    finally:
        await _drain(service)

    revived = opened[0]
    assert all(managed is revived for managed in opened)

    long = statuses(revived.conversation)["Long"]
    assert (long.status, long.stop_reason, long.report) == (
        "failed",
        "interrupted",
        "Halfway: read the README.",
    )
    ended = results(revived.conversation)["Long"]
    assert ended.to_chat_message()["content"].startswith(
        "[worker result] Long (explore, id "
    )
    assert "was interrupted by a server restart" in ended.to_chat_message()["content"]
    persisted = await conversations.list_events("c1")
    assert [row.kind for row in persisted[-2:]] == ["worker_status", "worker_result"]
    assert [row.kind for row in persisted].count("worker_result") == 1
    assert revived.persisted_seq == len(persisted)
