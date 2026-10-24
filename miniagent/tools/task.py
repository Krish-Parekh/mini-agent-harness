from __future__ import annotations

import shlex
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Literal

from pydantic import BaseModel, Field

from miniagent.agent import SPILL_ROOT, Agent, exclude_from_git
from miniagent.conversation import Conversation
from miniagent.events import ActionEvent, Event, MessageEvent, WorkerState
from miniagent.prompts import EXPLORE_WORKER_PROMPT, FORK_WORKER_PROMPT
from miniagent.sandbox.base import Sandbox, WorkdirView
from miniagent.sandbox.workspace import BRANCH_PREFIX, COMMITTER, SNAPSHOT, WorkspaceError
from miniagent.schema import Action, Observation
from miniagent.tools.base import Tool, ToolContext, ToolRegistry
from miniagent.tools.worker import Worker
from miniagent.tracing import bind_context

WORKERS_DIR = f"{SPILL_ROOT}/workers"
_GIT_TIMEOUT = 120


class TaskSpec(BaseModel):
    kind: Literal["explore", "fork"] = Field(
        description="`explore`: a fresh read-only agent that sees none of this "
        "conversation. `fork`: a copy of you that inherits this conversation and "
        "edits code in its own git worktree."
    )
    title: str = Field(description="Short label (3-5 words) shown to the user.")
    prompt: str = Field(
        description="The worker's brief. For `explore`, include every piece of "
        "context it needs. For `fork`, state the one change to make and what to "
        "report."
    )


class TaskAction(Action):
    tasks: list[TaskSpec] = Field(
        min_length=1,
        max_length=4,
        description="Independent workers to run in parallel.",
    )


class TaskObservation(Observation):
    workers: list[WorkerState]

    def to_llm_text(self) -> str:
        return "\n\n".join(_describe(worker) for worker in self.workers)

    def ui_details(self) -> dict[str, Any]:
        return {"workers": [worker.model_dump() for worker in self.workers]}


def _describe(worker: WorkerState) -> str:
    lines = [
        f"## {worker.title} ({worker.worker_kind}, {worker.status})",
        worker.report or "The worker ended without calling `finish` and left no report.",
    ]
    if worker.merged:
        lines.append(f"Merged into the workspace: {', '.join(worker.files)}.")
    elif worker.conflict:
        lines.append(
            f"Not merged: it conflicts with the workspace. Its commit stays on "
            f"branch {worker.branch}.\n{worker.conflict}"
        )
    elif worker.files:
        lines.append(
            f"Not merged because it did not finish. Its changes to "
            f"{', '.join(worker.files)} stay on branch {worker.branch}."
        )
    return "\n".join(lines)


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
    def __init__(self, sandbox: Sandbox, conversation_id: str) -> None:
        self._sandbox = sandbox
        self._conversation_id = conversation_id
        exclude_from_git(sandbox)
        self.head = self._git("git rev-parse --verify HEAD")
        self.base = self._git(SNAPSHOT)

    def _git(self, command: str, workdir: str | None = None) -> str:
        result = self._sandbox.run_command(command, timeout=_GIT_TIMEOUT, workdir=workdir)
        if result.exit_code != 0:
            raise WorkspaceError(
                f"fork git step failed: {(result.stderr or result.stdout).strip()[:300]}"
            )
        return result.stdout.strip()

    @staticmethod
    def path(worker_id: str) -> str:
        return f"{WORKERS_DIR}/{worker_id}"

    def add(self, worker_id: str) -> str:
        branch = f"{BRANCH_PREFIX}/{self._conversation_id}-w-{worker_id}"
        self._git(
            f"git worktree add -q -b {shlex.quote(branch)} "
            f"{shlex.quote(self.path(worker_id))} {self.base}"
        )
        return branch

    def commit(self, worker_id: str, title: str) -> list[str]:
        workdir = self.path(worker_id)
        self._git(
            f"git add -A && {{ git diff --cached --quiet || "
            f"git {COMMITTER} commit -q -m {shlex.quote(title)}; }}",
            workdir,
        )
        return self._git(f"git diff --name-only {self.base} HEAD", workdir).splitlines()

    def merge(self, workers: list[Worker]) -> None:
        self._git(f"git reset -q {self.base}")
        try:
            for worker in workers:
                result = self._sandbox.run_command(
                    f"git {COMMITTER} merge --no-edit {shlex.quote(worker.state.branch)}",
                    timeout=_GIT_TIMEOUT,
                )
                if result.exit_code == 0:
                    worker.publish(merged=True)
                    continue
                self._git(
                    "if git rev-parse -q --verify MERGE_HEAD >/dev/null; "
                    "then git merge --abort; fi"
                )
                worker.publish(conflict=(result.stdout + result.stderr).strip())
        finally:
            self._git(f"git reset -q {self.head}")

    def remove(self, worker_id: str) -> None:
        self._git(f"git worktree remove --force {shlex.quote(self.path(worker_id))}")


class TaskTool(Tool):
    name = "task"
    description = (
        "Run 1-4 worker agents in parallel and wait for all of them. "
        "kind='explore' starts a fresh read-only agent for a wide search or "
        "investigation; it has not seen this conversation, so its prompt must "
        "carry the context it needs. kind='fork' starts a copy of you that "
        "inherits this conversation and has your coding tools, working in its own "
        "git worktree. When the forks finish, each one's changes are merged into "
        "the workspace in order; a fork that conflicts stays on its branch and is "
        "reported. Give parallel forks independent changes in different files. "
        "Workers cannot ask the user anything or start workers of their own, and "
        "each returns its `finish` message as its report."
    )
    action_type = TaskAction
    observation_type = TaskObservation

    def __init__(
        self,
        tools: Callable[[], list[Tool]],
        fork_iterations: int = 30,
        explore_iterations: int = 8,
    ) -> None:
        self._tools = tools
        self.fork_iterations = fork_iterations
        self.explore_iterations = explore_iterations

    def execute(
        self, action: TaskAction, sandbox: Sandbox, context: ToolContext
    ) -> TaskObservation:
        forks = (
            Forks(sandbox, context.conversation.id)
            if any(spec.kind == "fork" for spec in action.tasks)
            else None
        )
        workers: list[Worker] = []
        try:
            for spec in action.tasks:
                workers.append(
                    self._fork(spec, sandbox, context, forks)
                    if spec.kind == "fork"
                    else self._explore(spec, sandbox, context)
                )
            with ThreadPoolExecutor(max_workers=len(workers)) as pool:
                runs = [
                    pool.submit(bind_context(self._run), worker, spec, forks)
                    for worker, spec in zip(workers, action.tasks)
                ]
                for run in runs:
                    run.result()
            finished = [
                worker
                for worker in workers
                if worker.state.worker_kind == "fork"
                and worker.state.status == "done"
                and worker.state.files
            ]
            if finished:
                forks.merge(finished)
        finally:
            for worker in workers:
                if worker.state.worker_kind == "fork":
                    forks.remove(worker.state.worker_id)
        return TaskObservation(workers=[worker.state for worker in workers])

    def _agent(self, parent: Conversation, system_prompt: str) -> Agent:
        return Agent(
            llm=parent.agent.llm,
            tools=ToolRegistry(self._tools()),
            system_prompt=system_prompt,
            repo=parent.agent.repo,
            branch=parent.agent.branch,
            policy=parent.agent.policy,
        )

    def _explore(self, spec: TaskSpec, sandbox: Sandbox, context: ToolContext) -> Worker:
        worker = Worker(
            context,
            WorkerState(worker_kind="explore", title=spec.title),
            self._agent(context.conversation, EXPLORE_WORKER_PROMPT),
            sandbox,
            max_iterations=self.explore_iterations,
            read_only=True,
        )
        worker.publish()
        return worker

    def _fork(
        self, spec: TaskSpec, sandbox: Sandbox, context: ToolContext, forks: Forks
    ) -> Worker:
        parent = context.conversation
        state = WorkerState(worker_kind="fork", title=spec.title, base=forks.base)
        state = state.model_copy(update={"branch": forks.add(state.worker_id)})
        worker = Worker(
            context,
            state,
            self._agent(parent, parent.agent.system_prompt),
            WorkdirView(sandbox, forks.path(state.worker_id)),
            max_iterations=self.fork_iterations,
            directive=FORK_WORKER_PROMPT,
            history=parent.events[: _step_start(parent.events, context.tool_call_id)],
        )
        worker.publish()
        return worker

    @staticmethod
    def _run(worker: Worker, spec: TaskSpec, forks: Forks | None) -> None:
        status, report = worker.run(spec.prompt)
        if spec.kind == "explore":
            worker.publish(status=status, report=report)
            return
        files = forks.commit(worker.state.worker_id, spec.title)
        worker.publish(status=status, report=report, files=files)
