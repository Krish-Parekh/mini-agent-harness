from __future__ import annotations

import logging
import posixpath
import shlex
import threading
from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from miniagent.agent import SPILL_ROOT, Agent, exclude_from_git
from miniagent.conversation import Conversation
from miniagent.events import (
    ActionEvent,
    Event,
    MessageEvent,
    WorkerEvent,
    WorkerState,
    WorkerStatusEvent,
)
from miniagent.prompts import EXPLORE_WORKER_PROMPT, FORK_WORKER_PROMPT
from miniagent.sandbox.base import Sandbox, WorkdirView
from miniagent.sandbox.workspace import (
    BRANCH_PREFIX,
    COMMITTER,
    SNAPSHOT,
    WorkspaceError,
    snapshot_onto,
)
from miniagent.schema import Action, Observation
from miniagent.tools.base import Tool, ToolContext, ToolRegistry
from miniagent.tools.worker import Worker
from miniagent.tools.workers import MAX_WORKERS

WORKERS_DIR = f"{SPILL_ROOT}/workers"
LINKED_DEPENDENCIES = ("node_modules", ".venv", "venv")
WORKER_EXCLUDED = frozenset({"task", "ask_user", "present_plan", "update_plan", "propose_skills"})
_GIT_TIMEOUT = 120
_log = logging.getLogger(__name__)


class TaskSpec(BaseModel):
    kind: Literal["explore", "fork"] | None = Field(
        default=None,
        description="`explore`: a fresh read-only agent that sees none of this "
        "conversation. `fork`: a copy of you that inherits this conversation and "
        "edits code in its own git worktree. Leave unset when resuming.",
    )
    title: str | None = Field(
        default=None,
        description="Short label (3-5 words) shown to the user. Leave unset when resuming.",
    )
    prompt: str = Field(
        description="The worker's brief. For `explore`, include every piece of "
        "context it needs. For `fork`, state the one change to make and what to "
        "report. When resuming, the follow-up instruction."
    )
    resume: str | None = Field(
        default=None,
        description="Id of a worker that stopped (partial, failed or cancelled) to "
        "continue with its own history; `prompt` is the follow-up.",
    )

    @model_validator(mode="after")
    def _new_worker_needs_kind_and_title(self) -> TaskSpec:
        if self.resume is None and (self.kind is None or not self.title):
            raise ValueError("a new worker needs `kind` and `title`")
        return self


class TaskAction(Action):
    tasks: list[TaskSpec] = Field(
        min_length=1,
        max_length=MAX_WORKERS,
        description="Independent workers to start in the background.",
    )


class TaskObservation(Observation):
    workers: list[WorkerState]

    def to_llm_text(self) -> str:
        started = "\n".join(
            f"- {w.title} ({w.worker_kind}, id {w.worker_id})" for w in self.workers
        )
        return (
            f"Started {len(self.workers)} worker(s) in the background:\n{started}\n"
            "Each result arrives as a `[worker result]` message when that worker "
            "ends. Keep working on anything that does not depend on them. If only "
            "waiting remains, end your turn instead of polling."
        )

    def ui_details(self) -> dict[str, Any]:
        return {"workers": [worker.model_dump() for worker in self.workers]}


def _step_start(events: list[Event], tool_call_id: str) -> int:
    index = next(
        i
        for i, event in enumerate(events)
        if isinstance(event, ActionEvent) and event.tool_call_id == tool_call_id
    )
    while index > 0 and (
        isinstance(events[index - 1], ActionEvent)
        or (isinstance(events[index - 1], MessageEvent) and events[index - 1].role == "assistant")
    ):
        index -= 1
    return index


class Forks:
    def __init__(
        self, sandbox: Sandbox, conversation_id: str, lock: threading.Lock, live: set[str]
    ) -> None:
        self._sandbox = sandbox
        self._conversation_id = conversation_id
        self._lock = lock
        self._links: dict[str, list[str]] = {}
        exclude_from_git(sandbox)
        self._prune(live)

    def _prune(self, live: set[str]) -> None:
        """Remove worktrees of workers that died with an earlier server process."""
        listed = self._run(f"ls -1 {WORKERS_DIR} 2>/dev/null").stdout.split()
        stale = [shlex.quote(self.path(w)) for w in listed if w not in live]
        if stale:
            self._git(f"rm -rf {' '.join(stale)}")
        self._git("git worktree prune")

    def _run(self, command: str, workdir: str | None = None):
        # Workers end on their own threads while the parent merges; git's lock
        # files on the shared repository would make concurrent steps fail.
        with self._lock:
            return self._sandbox.run_command(command, timeout=_GIT_TIMEOUT, workdir=workdir)

    def _git(self, command: str, workdir: str | None = None) -> str:
        result = self._run(command, workdir)
        if result.exit_code != 0:
            raise WorkspaceError(
                f"fork git step failed: {(result.stderr or result.stdout).strip()[:300]}"
            )
        return result.stdout.strip()

    def snapshot(self) -> str:
        return self._git(SNAPSHOT)

    @staticmethod
    def path(worker_id: str) -> str:
        return f"{WORKERS_DIR}/{worker_id}"

    def add(self, worker_id: str, base: str) -> str:
        branch = f"{BRANCH_PREFIX}/{self._conversation_id}-w-{worker_id}"
        self._git(
            f"git worktree add -q -b {shlex.quote(branch)} "
            f"{shlex.quote(self.path(worker_id))} {shlex.quote(base)}"
        )
        self._link_dependencies(worker_id)
        return branch

    def reattach(self, worker_id: str, branch: str) -> None:
        self._git(
            f"git worktree add -q {shlex.quote(self.path(worker_id))} {shlex.quote(branch)}"
        )
        self._link_dependencies(worker_id)

    def _link_dependencies(self, worker_id: str) -> None:
        ignored = self._git("git ls-files -oi --exclude-standard --directory").splitlines()
        links = [
            entry.rstrip("/")
            for entry in ignored
            if entry.endswith("/") and posixpath.basename(entry.rstrip("/")) in LINKED_DEPENDENCIES
        ]
        root = self._sandbox.workspace_dir
        for link in links:
            target = posixpath.join(self.path(worker_id), link)
            self._git(
                f"mkdir -p {shlex.quote(posixpath.dirname(target))} && "
                f"ln -s {shlex.quote(posixpath.join(root, link))} {shlex.quote(target)}"
            )
        self._links[worker_id] = links

    def commit(self, worker: Worker) -> list[str]:
        worker_id = worker.state.worker_id
        workdir = self.path(worker_id)
        excluded = "".join(
            f" {shlex.quote(f':(exclude){link}')}" for link in self._links.get(worker_id, [])
        )
        self._git(
            f"git add -A -- .{excluded} && {{ git diff --cached --quiet || "
            f"git {COMMITTER} commit -q -m {shlex.quote(worker.state.title)}; }}",
            workdir,
        )
        return self._git(
            f"git diff --name-only {shlex.quote(worker.state.base)} HEAD", workdir
        ).splitlines()

    def merge(self, worker: Worker) -> dict[str, Any]:
        """3-way merge of the fork into the parent's working tree, with the
        fork's base as merge base, so parent edits made while the fork ran are
        kept. Only the working tree changes: no ref, index or HEAD moves."""
        now = self._git(snapshot_onto(worker.state.base))
        result = self._run(
            f"git merge-tree --write-tree --name-only --no-messages {now} "
            f"{shlex.quote(worker.state.branch)}"
        )
        if result.exit_code == 1:
            files = result.stdout.strip().splitlines()[1:]
            return {"conflict": "Conflicting files: " + ", ".join(files)}
        if result.exit_code != 0:
            raise WorkspaceError(f"fork merge failed: {result.stderr.strip()[:300]}")
        tree = result.stdout.strip().splitlines()[0]
        self._git(f"git diff --binary {now} {tree} | git apply --binary --allow-empty")
        return {"merged": True}

    def remove(self, worker_id: str) -> None:
        self._git(f"git worktree remove --force {shlex.quote(self.path(worker_id))}")


class TaskTool(Tool):
    name = "task"
    description = (
        f"Start 1-{MAX_WORKERS} worker agents in the background and return at once; "
        f"at most {MAX_WORKERS} run at a time. kind='explore' starts a fresh "
        "read-only agent for a wide search or investigation; it has not seen this "
        "conversation, so its prompt must carry the context it needs. kind='fork' "
        "starts a copy of you that inherits this conversation and has your tools, "
        "working in its own git worktree; forks are refused in plan mode. Each "
        "worker's result arrives later as a `[worker result]` message, and a fork's "
        "changes are merged into the workspace then; a fork that conflicts stays on "
        "its branch and is reported. Give parallel forks independent changes in "
        "different files. Every result carries the worker's report, even when it "
        "stopped early (`partial`); continue such a worker with `resume` set to "
        "its id. Workers run under your permission mode, cannot ask the user "
        "anything, and cannot start workers of their own."
    )
    action_type = TaskAction
    observation_type = TaskObservation

    def __init__(
        self,
        tools: Callable[[], list[Tool]],
        fork_iterations: int = 150,
        explore_iterations: int = 50,
    ) -> None:
        self._tools = tools
        self.fork_iterations = fork_iterations
        self.explore_iterations = explore_iterations

    def execute(
        self, action: TaskAction, sandbox: Sandbox, context: ToolContext
    ) -> TaskObservation:
        parent = context.conversation
        previous = {spec.resume: self._previous(parent, spec.resume) for spec in action.tasks if spec.resume}
        kinds = [previous[spec.resume].worker_kind if spec.resume else spec.kind for spec in action.tasks]
        if parent.plan_mode and "fork" in kinds:
            raise ValueError(
                "Plan mode is on, and forks edit the workspace. Use explore workers, "
                "or present the plan first."
            )
        parent.workers.reserve(len(action.tasks))
        forks = (
            Forks(sandbox, parent.id, parent.workers.git_lock, parent.workers.live_ids())
            if "fork" in kinds
            else None
        )
        base = forks.snapshot() if forks and any(
            k == "fork" and not s.resume for k, s in zip(kinds, action.tasks)
        ) else None
        workers: list[tuple[Worker, str]] = []
        for spec in action.tasks:
            state = previous.get(spec.resume) if spec.resume else None
            worker = (
                self._resume(state, context, sandbox, forks)
                if state is not None
                else self._fork(spec, context, sandbox, forks, base)
                if spec.kind == "fork"
                else self._explore(spec, context, sandbox)
            )
            workers.append((worker, spec.prompt))
        for worker, prompt in workers:
            worker.publish()
            parent.workers.start(worker, _runner(worker, prompt))
        return TaskObservation(workers=[worker.state for worker, _ in workers])

    @staticmethod
    def _previous(parent: Conversation, worker_id: str) -> WorkerState:
        states = [
            e for e in parent.events if isinstance(e, WorkerStatusEvent) and e.worker_id == worker_id
        ]
        if not states:
            raise ValueError(f"No worker with id {worker_id}.")
        if parent.workers.is_live(worker_id):
            raise ValueError(f"Worker {worker_id} is still running.")
        last = states[-1]
        if last.merged:
            raise ValueError(
                f"Worker {worker_id} was already merged; start a new fork for more changes."
            )
        if last.worker_kind == "research":
            raise ValueError(f"Worker {worker_id} is a research worker and cannot be resumed.")
        return WorkerState(
            **last.model_dump(include=set(WorkerState.model_fields)) | {
                "status": "running",
                "stop_reason": None,
                "report": None,
                "conflict": None,
            }
        )

    def _agent(self, parent: Conversation, system_prompt: str) -> Agent:
        own = self._tools()
        names = {tool.name for tool in own} | WORKER_EXCLUDED
        agent = Agent(
            llm=parent.agent.llm,
            tools=ToolRegistry(own + [t for t in parent.agent.tools.all() if t.name not in names]),
            system_prompt=system_prompt,
            repo=parent.agent.repo,
            branch=parent.agent.branch,
            policy=parent.agent.policy,
        )
        agent.skills_block = parent.agent.skills_block
        agent.mcp_instructions = parent.agent.mcp_instructions
        return agent

    def _explore(
        self,
        spec: TaskSpec,
        context: ToolContext,
        sandbox: Sandbox,
        state: WorkerState | None = None,
        history: list[Event] | None = None,
    ) -> Worker:
        return Worker(
            context,
            state or WorkerState(worker_kind="explore", title=spec.title),
            self._agent(context.conversation, EXPLORE_WORKER_PROMPT),
            sandbox,
            max_iterations=self.explore_iterations,
            read_only=True,
            history=history or [],
        )

    def _fork(
        self,
        spec: TaskSpec,
        context: ToolContext,
        sandbox: Sandbox,
        forks: Forks,
        base: str,
    ) -> Worker:
        parent = context.conversation
        state = WorkerState(worker_kind="fork", title=spec.title, base=base)
        state = state.model_copy(update={"branch": forks.add(state.worker_id, base)})
        return self._fork_worker(
            context, sandbox, forks, state, parent.events[: _step_start(parent.events, context.tool_call_id)]
        )

    def _fork_worker(
        self,
        context: ToolContext,
        sandbox: Sandbox,
        forks: Forks,
        state: WorkerState,
        history: list[Event],
    ) -> Worker:
        parent = context.conversation
        view = WorkdirView(sandbox, forks.path(state.worker_id))
        worker = Worker(
            context,
            state,
            self._agent(parent, parent.agent.system_prompt),
            view,
            max_iterations=self.fork_iterations,
            directive=FORK_WORKER_PROMPT.format(
                worktree=view.workspace_dir, parent=sandbox.workspace_dir
            ),
            history=history,
        )
        worker.on_end = lambda w: _end_fork(forks, w)
        worker.on_deliver = lambda w: _deliver_fork(forks, w)
        return worker

    def _resume(
        self,
        state: WorkerState,
        context: ToolContext,
        sandbox: Sandbox,
        forks: Forks | None,
    ) -> Worker:
        parent = context.conversation
        own = [
            e.event
            for e in parent.events
            if isinstance(e, WorkerEvent) and e.worker_id == state.worker_id
        ]
        if state.worker_kind == "explore":
            return self._explore(None, context, sandbox, state, own)
        first_call = next(
            e.parent_tool_call_id
            for e in parent.events
            if isinstance(e, WorkerStatusEvent) and e.worker_id == state.worker_id
        )
        forks.reattach(state.worker_id, state.branch)
        inherited = parent.events[: _step_start(parent.events, first_call)]
        return self._fork_worker(context, sandbox, forks, state, inherited + own)


def _runner(worker: Worker, prompt: str) -> Callable[[], None]:
    def run() -> None:
        try:
            worker.run(prompt)
        except Exception as exc:
            worker.publish(status="failed", stop_reason="error", report=f"The worker crashed: {exc}")

    return run


def _end_fork(forks: Forks, worker: Worker) -> dict[str, Any]:
    try:
        return {"files": forks.commit(worker)}
    finally:
        try:
            forks.remove(worker.state.worker_id)
        except WorkspaceError as exc:
            _log.warning("could not remove worktree of worker %s: %s", worker.state.worker_id, exc)


def _deliver_fork(forks: Forks, worker: Worker) -> dict[str, Any]:
    if worker.state.status != "done" or not worker.state.files:
        return {}
    try:
        return forks.merge(worker)
    except WorkspaceError as exc:
        return {"conflict": str(exc)}

