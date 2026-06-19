from __future__ import annotations

from importlib.resources import files


def _load(name: str) -> str:
    return (files(__package__) / name).read_text(encoding="utf-8")


DEFAULT_SYSTEM_PROMPT = _load("system.md")
PLAN_MODE_DIRECTIVE = _load("plan_mode.md")
IMPLEMENT_PLAN_DIRECTIVE = _load("implement_plan.md")
EARLY_STOP_PROMPT = _load("early_stop.md")
CONDENSE_SYSTEM_PROMPT = _load("condense.md")
ROUTE_QUESTION_DIRECTIVE = _load("route_question.md")
ROUTE_CODE_EDIT_DIRECTIVE = _load("route_code_edit.md")
ROUTE_REVIEW_DIRECTIVE = _load("route_review.md")
ROUTE_PR_FLOW_DIRECTIVE = _load("route_pr_flow.md")
WEB_RESEARCH_WORKER_PROMPT = _load("web_research_worker.md")
