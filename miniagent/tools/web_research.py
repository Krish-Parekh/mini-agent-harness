from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from pydantic import Field

from miniagent.agent import Agent
from miniagent.classification import StaticTaskClassifier
from miniagent.confirm import ConfirmPolicy
from miniagent.conversation import Conversation
from miniagent.events import ActionEvent, FanoutWorkerEvent, MessageEvent, ObservationEvent
from miniagent.llm import LLM
from miniagent.prompts import WEB_RESEARCH_WORKER_PROMPT
from miniagent.sandbox.base import Sandbox
from miniagent.schema import Action, Observation
from miniagent.tools.base import Tool, ToolRegistry
from miniagent.tools.fetch_url import FetchUrlTool
from miniagent.tools.finish import FinishTool
from miniagent.tools.web_search import WebSearchTool

if TYPE_CHECKING:
    pass


class WebResearchAction(Action):
    prompt: str = Field(
        description="The web research task to investigate and summarize."
    )
    description: str | None = Field(
        default=None,
        description="Optional short label (3-5 words) for the research task.",
    )


class WebResearchObservation(Observation):
    summary: str
    status: str
    error: bool = False

    def to_llm_text(self) -> str:
        label = self.status
        return f"Web research ({label}):\n{self.summary}"


def _describe_worker_activity(event: ActionEvent) -> str | None:
    if event.tool_name == "web_search":
        query = str(event.arguments.get("query", "")).strip()
        return f"Searching: {query[:100]}" if query else "Searching the web"
    if event.tool_name == "fetch_url":
        url = str(event.arguments.get("url", "")).strip()
        return f"Fetching {url[:100]}" if url else "Fetching URL"
    if event.tool_name == "finish":
        return "Writing summary"
    return None


class WebResearchTool(Tool):
    name = "web_research"
    description = (
        "Delegate a web research task to a read-only specialist agent. Use this "
        "when you need documentation, API references, changelogs, Stack Overflow "
        "answers, or other public web information outside the workspace. The "
        "specialist searches with Tavily, fetches relevant pages, and returns a "
        "structured summary with source URLs."
    )
    action_type = WebResearchAction
    observation_type = WebResearchObservation

    def __init__(
        self,
        llm: LLM,
        web_search: WebSearchTool,
        fetch_url: FetchUrlTool,
        max_iterations: int = 10,
    ) -> None:
        self.llm = llm
        self.web_search = web_search
        self.fetch_url = fetch_url
        self.max_iterations = max_iterations

    def execute(
        self,
        action: WebResearchAction,
        sandbox: Sandbox,
        *,
        conversation: Conversation | None = None,
        tool_call_id: str | None = None,
    ) -> WebResearchObservation:
        title = (action.description or "Web research").strip() or "Web research"
        emit_lock = threading.Lock()

        def emit(status: str, activity: str | None = None) -> None:
            if conversation is None or tool_call_id is None:
                return
            with emit_lock:
                conversation.add_event(
                    FanoutWorkerEvent(
                        parent_tool_call_id=tool_call_id,
                        worker_index=0,
                        title=title,
                        status=status,  # type: ignore[arg-type]
                        activity=activity,
                    )
                )

        emit("running", "Spawned")

        def on_worker_event(event) -> None:
            if isinstance(event, ActionEvent):
                activity = _describe_worker_activity(event)
                if activity:
                    emit("running", activity)

        agent = Agent(
            llm=self.llm,
            tools=self._worker_tools(),
            system_prompt=WEB_RESEARCH_WORKER_PROMPT,
            task_router=StaticTaskClassifier(),
        )
        worker = Conversation(
            agent=agent,
            sandbox=sandbox,
            on_event=on_worker_event,
            max_iterations=self.max_iterations,
            confirm_policy=ConfirmPolicy("never"),
        )
        try:
            emit("running", "Starting investigation")
            worker.send_message(action.prompt)
            worker.run()
            summary = self._worker_summary(worker)
            status = "error" if worker.status.value in ("error", "stuck") else "done"
            emit(status, "Completed" if status == "done" else "Failed")
            return WebResearchObservation(
                summary=summary,
                status=worker.status.value,
                error=status == "error",
            )
        except Exception as exc:
            emit("error", f"Failed: {exc}")
            return WebResearchObservation(
                summary=str(exc),
                status="error",
                error=True,
            )

    def _worker_tools(self) -> ToolRegistry:
        return ToolRegistry(
            [
                self.web_search,
                self.fetch_url,
                FinishTool(),
            ]
        )

    @staticmethod
    def _worker_summary(conversation: Conversation) -> str:
        for event in reversed(conversation.events):
            if isinstance(event, ObservationEvent) and event.tool_name == "finish":
                return event.content
            if (
                isinstance(event, MessageEvent)
                and event.role == "assistant"
                and event.text.strip()
            ):
                return event.text.strip()
        errors = [
            event.content
            for event in conversation.events
            if isinstance(event, ObservationEvent) and event.error
        ]
        if errors:
            return errors[-1]
        return "Web research ended without a finish summary."
