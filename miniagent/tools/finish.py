from __future__ import annotations

from typing import TYPE_CHECKING, Any

from miniagent.events import ObservationEvent
from miniagent.sandbox.base import Sandbox
from miniagent.schema import Action, Observation
from miniagent.tools.base import Tool, ToolContext

if TYPE_CHECKING:
    from miniagent.conversation import Conversation


class FinishAction(Action):
    message: str


class FinishObservation(Observation):
    message: str
    checklist: bool = False

    @property
    def error(self) -> bool:
        return self.checklist

    def to_llm_text(self) -> str:
        return self.message

    def ui_details(self) -> dict[str, Any] | None:
        return {"checklist": True} if self.checklist else None


class FinishTool(Tool):
    name = "finish"
    description = (
        "Call this when the task is complete to end the conversation. "
        "Provide a short summary of what was done in 'message'."
    )
    action_type = FinishAction
    observation_type = FinishObservation

    def __init__(self, checklist: str | None = None) -> None:
        self.checklist = checklist

    def execute(
        self, action: FinishAction, sandbox: Sandbox, context: ToolContext
    ) -> FinishObservation:
        if self.checklist and not _follows_checklist(context.conversation):
            return FinishObservation(message=self.checklist, checklist=True)
        return FinishObservation(message=action.message)


def _follows_checklist(conversation: Conversation) -> bool:
    observations = [e for e in conversation.live_events() if isinstance(e, ObservationEvent)]
    return bool(observations) and (observations[-1].details or {}).get("checklist", False)
