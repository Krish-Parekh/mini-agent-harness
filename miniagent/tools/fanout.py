from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from pydantic import BaseModel, Field

from miniagent.agent import Agent
from miniagent.classification import StaticTaskClassifier
from miniagent.confirm import ConfirmPolicy
from miniagent.conversation import Conversation
from miniagent.events import MessageEvent, ObservationEvent
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

    def execute(self, action: FanoutAction, sandbox: Sandbox) -> FanoutObservation:
        with ThreadPoolExecutor(max_workers=len(action.tasks)) as executor:
            results = list(
                executor.map(lambda task: self._run_worker(task, sandbox), action.tasks)
            )
        return FanoutObservation(results=results)

    def _run_worker(self, task: FanoutTask, sandbox: Sandbox) -> WorkerResult:
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
            max_iterations=self.max_iterations,
            confirm_policy=ConfirmPolicy("never"),
        )
        conversation.send_message(task.prompt)
        conversation.run()
        return WorkerResult(
            title=task.title,
            status=conversation.status.value,
            summary=self._worker_summary(conversation),
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
