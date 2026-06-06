from __future__ import annotations

from miniagent.sandbox.base import Sandbox
from miniagent.schema import Action, Observation
from miniagent.tools.base import Tool


class FinishAction(Action):
    message: str


class FinishObservation(Observation):
    message: str

    def to_llm_text(self) -> str:
        return self.message


class FinishTool(Tool):
    name = "finish"
    description = (
        "Call this when the task is complete to end the conversation. "
        "Provide a short summary of what was done in 'message'."
    )
    action_type = FinishAction
    observation_type = FinishObservation

    def execute(self, action: FinishAction, sandbox: Sandbox) -> FinishObservation:
        return FinishObservation(message=action.message)
