from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from miniagent.agent import Agent
from miniagent.classification import StaticTaskClassifier
from miniagent.confirm import ConfirmPolicy
from miniagent.conversation import Conversation
from miniagent.events import ActionEvent, FanoutWorkerEvent, MessageEvent, ObservationEvent
from miniagent.llm import LLM
from miniagent.policy import PolicyClassifier, PolicyProvider
from miniagent.sandbox.base import Sandbox
from miniagent.schema import Action, Observation
from miniagent.skills import SkillLibrary
from miniagent.tools.base import Tool, ToolRegistry
from miniagent.tools.bash import BashAction, BashObservation, BashTool
from miniagent.tools.file_edit import FileEditAction, FileEditObservation, FileEditTool
from miniagent.tools.finish import FinishTool
from miniagent.tools.skill import ReadSkillTool

if TYPE_CHECKING:
    pass

_WORKER_SYSTEM_PROMPT = """You are a read-only MiniAgent worker.

Investigate the assigned subtask using only read/search tools. Do not modify
files, install packages, commit, push, or ask the user. When done, call `finish`
with a concise summary of the facts, relevant files, commands run, and any
uncertainty.
"""


class FanoutTask(BaseModel):
    title: str = Field(description="Short label for the worker task.")
    prompt: str = Field(description="Focused read-only investigation for the worker.")


class FanoutAction(Action):
    tasks: list[FanoutTask] = Field(
        min_length=1,
        max_length=4,
        description="Independent read-only worker tasks to run and summarize.",
    )


class WorkerResult(BaseModel):
    title: str
    status: str
    summary: str


class FanoutObservation(Observation):
    results: list[WorkerResult]
    error: bool = False

    def to_llm_text(self) -> str:
        lines = ["Read-only worker results:"]
        for result in self.results:
            lines.append(f"\n## {result.title} ({result.status})\n{result.summary}")
        return "\n".join(lines)


class ReadOnlyBashTool(BashTool):
    description = BashTool.description + " This worker instance rejects mutating commands."

    def __init__(self, policy: PolicyProvider) -> None:
        self.policy = policy

    def execute(self, action: BashAction, sandbox: Sandbox) -> BashObservation:
        if not self.policy.classify_bash(action.command).read_only:
            return BashObservation(
                stdout="",
                stderr="Read-only worker rejected a mutating command.",
                exit_code=1,
                error=True,
            )
        return super().execute(action, sandbox)


class ReadOnlyFileEditTool(FileEditTool):
    description = FileEditTool.description + " This worker instance only allows view."

    def execute(self, action: FileEditAction, sandbox: Sandbox) -> FileEditObservation:
        if action.command != "view":
            return FileEditObservation(
                output="Read-only worker rejected a file mutation.",
                error=True,
            )
        return super().execute(action, sandbox)


def _describe_worker_activity(event: ActionEvent) -> str | None:
    if event.tool_name == "bash":
        command = str(event.arguments.get("command", "")).strip()
        if not command:
            return "Running shell command"
        line = command.splitlines()[0]
        return f"Running: {line[:100]}"
    if event.tool_name == "file_edit":
        path = str(event.arguments.get("path", ""))
        if event.arguments.get("command") == "view":
            return f"Reading {path}" if path else "Reading file"
    if event.tool_name == "read_skill":
        name = str(event.arguments.get("name", ""))
        return f"Reading skill {name}" if name else "Reading skill"
    if event.tool_name == "finish":
        return "Writing summary"
    return None


class FanoutTool(Tool):
    name = "fanout"
    description = (
        "Run 1-4 independent read-only worker agents for exploration tasks, then "
        "return their summaries. Use this for broad searches, locating relevant "
        "files, identifying tests, or getting focused review perspectives before "
        "the parent agent decides what to do."
    )
    action_type = FanoutAction
    observation_type = FanoutObservation

    def __init__(
        self,
        llm: LLM,
        repo: str | None = None,
        branch: str | None = None,
        skills: SkillLibrary | None = None,
        policy: PolicyProvider | None = None,
        max_iterations: int = 8,
    ) -> None:
        self.llm = llm
        self.repo = repo
        self.branch = branch
        self.skills = skills
        self.policy = policy or PolicyClassifier(llm)
        self.max_iterations = max_iterations

    def execute(
        self,
        action: FanoutAction,
        sandbox: Sandbox,
        *,
        conversation: Conversation | None = None,
        tool_call_id: str | None = None,
    ) -> FanoutObservation:
        emit_lock = threading.Lock()

        def emit(
            index: int,
            title: str,
            status: str,
            activity: str | None = None,
        ) -> None:
            if conversation is None or tool_call_id is None:
                return
            with emit_lock:
                conversation.add_event(
                    FanoutWorkerEvent(
                        parent_tool_call_id=tool_call_id,
                        worker_index=index,
                        title=title,
                        status=status,  # type: ignore[arg-type]
                        activity=activity,
                    )
                )

        for index, task in enumerate(action.tasks):
            emit(index, task.title, "running", "Spawned")

        results: list[WorkerResult | None] = [None] * len(action.tasks)
        with ThreadPoolExecutor(max_workers=len(action.tasks)) as executor:
            futures = {
                executor.submit(
                    self._run_worker,
                    task,
                    sandbox,
                    index,
                    emit,
                ): index
                for index, task in enumerate(action.tasks)
            }
            for future in as_completed(futures):
                index = futures[future]
                results[index] = future.result()

        finalized: list[WorkerResult] = []
        for index, result in enumerate(results):
            if result is not None:
                finalized.append(result)
            else:
                finalized.append(
                    WorkerResult(
                        title=action.tasks[index].title,
                        status="error",
                        summary="Worker failed unexpectedly.",
                    )
                )
        return FanoutObservation(results=finalized)

    def _run_worker(
        self,
        task: FanoutTask,
        sandbox: Sandbox,
        index: int,
        emit,
    ) -> WorkerResult:
        emit(index, task.title, "running", "Starting investigation")

        def on_worker_event(event) -> None:
            if isinstance(event, ActionEvent):
                activity = _describe_worker_activity(event)
                if activity:
                    emit(index, task.title, "running", activity)

        agent = Agent(
            llm=self.llm,
            tools=self._worker_tools(),
            system_prompt=_WORKER_SYSTEM_PROMPT,
            repo=self.repo,
            branch=self.branch,
            skills=self.skills,
            policy=self.policy,
            task_router=StaticTaskClassifier(),
        )
        conversation = Conversation(
            agent=agent,
            sandbox=sandbox,
            on_event=on_worker_event,
            max_iterations=self.max_iterations,
            confirm_policy=ConfirmPolicy("never"),
        )
        try:
            conversation.send_message(task.prompt)
            conversation.run()
            summary = self._worker_summary(conversation)
            status = "error" if conversation.status.value in ("error", "stuck") else "done"
            activity = "Completed" if status == "done" else "Failed"
            emit(index, task.title, status, activity)
            return WorkerResult(
                title=task.title,
                status=conversation.status.value,
                summary=summary,
            )
        except Exception as exc:
            emit(index, task.title, "error", f"Failed: {exc}")
            return WorkerResult(
                title=task.title,
                status="error",
                summary=str(exc),
            )

    def _worker_tools(self) -> ToolRegistry:
        tools: list[Tool] = [
            ReadOnlyBashTool(self.policy),
            ReadOnlyFileEditTool(),
            FinishTool(),
        ]
        if self.skills is not None:
            tools.append(ReadSkillTool(self.skills, self.repo))
        return ToolRegistry(tools)

    @staticmethod
    def _worker_summary(conversation: Conversation) -> str:
        # Workers that call `finish` give us an explicit summary. Most instead
        # answer in a final assistant message and end the turn idle — capture
        # that so their findings aren't discarded.
        last_assistant: str | None = None
        for event in reversed(conversation.events):
            if isinstance(event, ObservationEvent) and event.tool_name == "finish":
                return event.content
            if (
                last_assistant is None
                and isinstance(event, MessageEvent)
                and event.role == "assistant"
                and event.text.strip()
            ):
                last_assistant = event.text.strip()
        if last_assistant:
            return last_assistant
        errors = [
            event.content
            for event in conversation.events
            if isinstance(event, ObservationEvent) and event.error
        ]
        if errors:
            return errors[-1]
        return "Worker ended without a finish summary."
