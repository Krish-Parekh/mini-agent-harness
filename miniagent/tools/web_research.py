from __future__ import annotations

from pydantic import Field

from miniagent.agent import Agent
from miniagent.events import WorkerState
from miniagent.llm import LLM
from miniagent.prompts import WEB_RESEARCH_WORKER_PROMPT
from miniagent.sandbox.base import Sandbox
from miniagent.schema import Action, Observation
from miniagent.tools.base import Tool, ToolContext, ToolRegistry
from miniagent.tools.fetch_url import FetchUrlTool
from miniagent.tools.finish import FinishTool
from miniagent.tools.web_search import WebSearchTool
from miniagent.tools.worker import Worker


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
        self, action: WebResearchAction, sandbox: Sandbox, context: ToolContext
    ) -> WebResearchObservation:
        worker = Worker(
            context,
            WorkerState(
                worker_kind="research",
                title=(action.description or "").strip() or "Web research",
            ),
            Agent(
                llm=self.llm,
                tools=ToolRegistry([self.web_search, self.fetch_url, FinishTool()]),
                system_prompt=WEB_RESEARCH_WORKER_PROMPT,
            ),
            sandbox,
            max_iterations=self.max_iterations,
        )
        worker.publish()
        status, report = worker.run(action.prompt)
        worker.publish(status=status, report=report)
        return WebResearchObservation(
            summary=report or "The researcher ended without calling `finish` and left no report.",
            status=status,
            error=status != "done",
        )
