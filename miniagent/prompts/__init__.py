from __future__ import annotations

from importlib.resources import files


def _load(name: str) -> str:
    return (files(__package__) / name).read_text(encoding="utf-8")


DEFAULT_SYSTEM_PROMPT = _load("system.md")
HEADLESS_SYSTEM_PROMPT = _load("headless.md")
FINISH_CHECKLIST_PROMPT = _load("finish_checklist.md")
PLAN_MODE_DIRECTIVE = _load("plan_mode.md")
IMPLEMENT_PLAN_DIRECTIVE = _load("implement_plan.md")
EARLY_STOP_PROMPT = _load("early_stop.md")
FINISH_NUDGE_PROMPT = _load("finish_nudge.md")
CONDENSE_SYSTEM_PROMPT = _load("condense.md")
WEB_RESEARCH_WORKER_PROMPT = _load("web_research_worker.md")
