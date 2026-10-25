from __future__ import annotations

from typing import Literal

from miniagent.agent import Agent, TimeBudget
from miniagent.config import Settings
from miniagent.llm import LLM
from miniagent.policy import PolicyClassifier
from miniagent.prompts import FINISH_CHECKLIST_PROMPT, HEADLESS_SYSTEM_PROMPT
from miniagent.tools.ask import AskUserTool
from miniagent.tools.base import Tool, ToolRegistry
from miniagent.tools.fetch_url import FetchUrlTool
from miniagent.tools.file_edit import FileEditTool
from miniagent.tools.find_skills import FindSkillsTool, ProposeSkillsTool
from miniagent.tools.finish import FinishTool
from miniagent.tools.memory import MemoryStore, MemoryTool
from miniagent.tools.plan import PresentPlanTool, UpdatePlanTool
from miniagent.tools.search import GlobTool, GrepTool
from miniagent.tools.task import TaskTool
from miniagent.tools.terminal import TerminalTool
from miniagent.tools.web_research import WebResearchTool
from miniagent.tools.web_search import WebSearchTool

Preset = Literal["interactive", "headless"]


def core_tools() -> list[Tool]:
    return [TerminalTool(), FileEditTool(), GrepTool(), GlobTool(), FinishTool()]


def build_agent(
    settings: Settings,
    *,
    preset: Preset,
    repo: str | None = None,
    branch: str | None = None,
    memory: MemoryStore | None = None,
    time_budget: TimeBudget | None = None,
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
    if preset == "headless":
        return Agent(
            llm=llm,
            tools=ToolRegistry(
                [
                    TerminalTool(),
                    FileEditTool(),
                    GrepTool(confined=False),
                    GlobTool(confined=False),
                    FinishTool(checklist=FINISH_CHECKLIST_PROMPT),
                ]
            ),
            system_prompt=HEADLESS_SYSTEM_PROMPT,
            policy=policy,
            time_budget=time_budget,
        )
    tools = core_tools() + [
        PresentPlanTool(),
        UpdatePlanTool(),
        AskUserTool(),
        TaskTool(
            core_tools,
            fork_iterations=settings.fork_iterations,
            explore_iterations=settings.explore_iterations,
        ),
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
