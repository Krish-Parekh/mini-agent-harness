from __future__ import annotations

from miniagent.sandbox.base import Sandbox
from miniagent.schema import Action, Observation
from miniagent.tools.base import Tool


class SkillAction(Action):
    name: str


class SkillObservation(Observation):
    content: str
    error: bool = False

    def to_llm_text(self) -> str:
        return self.content


class SkillTool(Tool):
    name = "skill"
    description = (
        "Load the full text of a skill the user enabled for this conversation. "
        "The runtime context lists the available skills by name and description; "
        "call this with a skill's name before doing a task it applies to, then "
        "follow it."
    )
    action_type = SkillAction
    observation_type = SkillObservation

    def __init__(self, bodies: dict[str, str]) -> None:
        self.bodies = bodies

    def execute(self, action: SkillAction, sandbox: Sandbox) -> SkillObservation:
        body = self.bodies.get(action.name)
        if body is None:
            available = ", ".join(sorted(self.bodies)) or "none"
            return SkillObservation(
                content=f"Unknown skill: {action.name}. Available: {available}",
                error=True,
            )
        return SkillObservation(content=body)
