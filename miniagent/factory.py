from __future__ import annotations

from typing import Literal

from miniagent.agent import Agent
from miniagent.config import Settings
from miniagent.llm import LLM
from miniagent.policy import PolicyClassifier
from miniagent.tools.ask import AskUserTool
from miniagent.tools.base import Tool, ToolRegistry
from miniagent.tools.bash import BashTool
from miniagent.tools.fetch_url import FetchUrlTool
from miniagent.tools.file_edit import FileEditTool
from miniagent.tools.find_skills import FindSkillsTool, ProposeSkillsTool
from miniagent.tools.finish import FinishTool
from miniagent.tools.memory import MemoryStore, MemoryTool
from miniagent.tools.plan import PresentPlanTool, UpdatePlanTool
from miniagent.tools.search import GlobTool, GrepTool
from miniagent.tools.task import TaskTool
from miniagent.tools.web_research import WebResearchTool
from miniagent.tools.web_search import WebSearchTool

Preset = Literal["interactive", "headless"]


def headless_tools() -> list[Tool]:
    return [BashTool(), FileEditTool(), GrepTool(), GlobTool(), FinishTool()]


def build_agent(
    settings: Settings,
    *,
    preset: Preset,
    repo: str | None = None,
    branch: str | None = None,
    memory: MemoryStore | None = None,
) -> Agent:
    llm = LLM(
        model=settings.model,
        temperature=settings.temperature,
        max_tokens=settings.max_tokens,
        reasoning_effort=settings.reasoning_effort,
    )
    policy = PolicyClassifier(
        LLM(model=settings.policy_model, temperature=0.0, max_tokens=1024)
    )
    tools = headless_tools()
    if preset == "interactive":
        tools += [
            PresentPlanTool(),
            UpdatePlanTool(),
            AskUserTool(),
            TaskTool(headless_tools),
            FindSkillsTool(),
            ProposeSkillsTool(),
        ]
        if settings.tavily_api_key:
            web_search = WebSearchTool(settings.tavily_api_key)
            fetch_url = FetchUrlTool()
            tools += [web_search, fetch_url, WebResearchTool(llm, web_search, fetch_url)]
        if memory is not None:
            tools.append(MemoryTool(memory))
    return Agent(
        llm=llm,
        tools=ToolRegistry(tools),
        repo=repo,
        branch=branch,
        policy=policy,
        memory=memory,
    )
