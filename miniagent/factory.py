from __future__ import annotations

from typing import Literal

from miniagent.agent import Agent, TimeBudget
from miniagent.config import Settings
from miniagent.llm import LLM
from miniagent.policy import PolicyClassifier
from miniagent.prompts import FINISH_CHECKLIST_PROMPT, HEADLESS_SYSTEM_PROMPT
from miniagent.tools.ask import AskUserTool
from miniagent.tools.base import Tool, ToolRegistry
from miniagent.tools.bash import BashTool
from miniagent.tools.fanout import FanoutTool
from miniagent.tools.fetch_url import FetchUrlTool
from miniagent.tools.file_edit import FileEditTool
from miniagent.tools.find_skills import FindSkillsTool, ProposeSkillsTool
from miniagent.tools.finish import FinishTool
from miniagent.tools.memory import MemoryStore, MemoryTool
from miniagent.tools.plan import PresentPlanTool, UpdatePlanTool
from miniagent.tools.search import GlobTool, GrepTool
from miniagent.tools.web_research import WebResearchTool
from miniagent.tools.web_search import WebSearchTool

Preset = Literal["interactive", "headless"]


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
        headless: list[Tool] = [
            BashTool(),
            FileEditTool(),
            GrepTool(confined=False),
            GlobTool(confined=False),
            FinishTool(checklist=FINISH_CHECKLIST_PROMPT),
        ]
        return Agent(
            llm=llm,
            tools=ToolRegistry(headless),
            system_prompt=HEADLESS_SYSTEM_PROMPT,
            policy=policy,
            time_budget=time_budget,
        )
    tools: list[Tool] = [
        BashTool(),
        FileEditTool(),
        GrepTool(),
        GlobTool(),
        FinishTool(),
        PresentPlanTool(),
        UpdatePlanTool(),
        AskUserTool(),
        FanoutTool(llm, repo, branch, policy),
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
        time_budget=time_budget,
    )
