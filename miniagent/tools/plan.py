from __future__ import annotations

from miniagent.sandbox.base import Sandbox
from miniagent.schema import Action, Observation
from miniagent.tools.base import Tool


class PresentPlanAction(Action):
    plan: str


class PresentPlanObservation(Observation):
    plan: str

    def to_llm_text(self) -> str:
        return (
            "Plan presented to the user. Stop here and wait for their go-ahead "
            "before implementing."
        )


class PresentPlanTool(Tool):
    name = "present_plan"
    description = (
        "Present an implementation plan to the user and pause for their review. "
        "Use this when planning mode is on: after exploring the code read-only, "
        "lay out in 'plan' (markdown) the goal, the files you'll touch, and the "
        "ordered steps you intend to take, then call this tool instead of editing "
        "files or finishing. The turn stops so the user can approve or refine the "
        "plan before you implement."
    )
    action_type = PresentPlanAction
    observation_type = PresentPlanObservation

    def execute(
        self, action: PresentPlanAction, sandbox: Sandbox
    ) -> PresentPlanObservation:
        return PresentPlanObservation(plan=action.plan)
