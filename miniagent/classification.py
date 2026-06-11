from __future__ import annotations

from enum import StrEnum
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict

from miniagent.llm import LLM


class TaskRoute(StrEnum):
    DEFAULT = "default"
    QUESTION = "question"
    PLAN = "plan"
    CODE_EDIT = "code_edit"
    REVIEW = "review"
    PR_FLOW = "pr_flow"


class TaskRouteProvider(Protocol):
    def classify_task_route(self, text: str) -> TaskRoute: ...


ClassifiedTaskRoute = Literal["default", "question", "code_edit", "review", "pr_flow"]


class TaskRouteDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    route: ClassifiedTaskRoute = "default"
    reason: str = ""


_TASK_ROUTE_SYSTEM = """You classify the user's next request for a coding agent.

Return a structured response with route and a short reason.

Routes:
- "question": the user primarily wants an explanation, answer, or guidance without edits.
- "code_edit": the user wants code, configuration, tests, or docs changed in the workspace.
- "review": the user asks for a code review, audit, issue finding, or risk assessment.
- "pr_flow": the user wants to create, open, raise, update, or manage a pull request.
- "default": use only when the request is vague, conversational, or does not clearly fit.

Do not return "plan"; planning mode is selected outside this classifier.
If uncertain, use route="default".
"""


class TaskClassifier:
    def __init__(self, llm: LLM) -> None:
        self.llm = llm
        self._cache: dict[str, TaskRoute] = {}

    def classify_task_route(self, text: str) -> TaskRoute:
        cached = self._cache.get(text)
        if cached is not None:
            return cached
        route = self._classify(text)
        self._cache[text] = route
        return route

    def _classify(self, text: str) -> TaskRoute:
        try:
            decision = self.llm.complete_structured(
                [
                    {"role": "system", "content": _TASK_ROUTE_SYSTEM},
                    {"role": "user", "content": f"User request:\n{text}"},
                ],
                TaskRouteDecision,
            )
        except Exception:
            return TaskRoute.DEFAULT
        return TaskRoute(decision.route)


class StaticTaskClassifier:
    def __init__(self, route: TaskRoute = TaskRoute.DEFAULT) -> None:
        self.route = route

    def classify_task_route(self, text: str) -> TaskRoute:
        return self.route
