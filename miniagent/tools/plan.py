from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from miniagent.sandbox.base import Sandbox
from miniagent.schema import Action, Observation
from miniagent.tools.base import Tool

StepStatus = Literal["pending", "in_progress", "done"]

_CHECKBOX = {"pending": "[ ]", "in_progress": "[~]", "done": "[x]"}


class PlanStep(BaseModel):
    title: str = Field(description="Imperative summary of the step, e.g. 'Add the lane column'")
    files: list[str] = Field(default_factory=list, description="Files this step touches")
    description: str = Field(default="", description="One or two sentences on what to do and why")
    status: StepStatus = "pending"


class Plan(BaseModel):
    title: str
    steps: list[PlanStep]

    def render(self) -> str:
        lines = [f"## {self.title}"]
        for i, step in enumerate(self.steps, 1):
            line = f"{i}. {_CHECKBOX[step.status]} {step.title}"
            if step.files:
                line += f" — {', '.join(step.files)}"
            lines.append(line)
            if step.description:
                lines.append(f"   {step.description}")
        return "\n".join(lines)


class PresentPlanAction(Action):
    title: str = Field(description="Short name for the overall plan")
    steps: list[PlanStep] = Field(description="Ordered implementation steps")


class PresentPlanObservation(Observation):
    title: str

    def to_llm_text(self) -> str:
        return (
            "Plan presented to the user. Stop here and wait for their go-ahead "
            "before implementing."
        )


class PresentPlanTool(Tool):
    name = "present_plan"
    description = (
        "Present a structured implementation plan to the user and pause for "
        "their review. Use this when planning mode is on: after exploring the "
        "code read-only, lay out the ordered steps — each with an imperative "
        "title, the files it touches, and a short description — then call this "
        "tool instead of editing files or finishing. The turn stops so the user "
        "can approve or refine the plan before you implement."
    )
    action_type = PresentPlanAction
    observation_type = PresentPlanObservation

    def execute(
        self, action: PresentPlanAction, sandbox: Sandbox
    ) -> PresentPlanObservation:
        return PresentPlanObservation(title=action.title)


class UpdatePlanAction(Action):
    step: int = Field(description="1-based index of the step, matching the plan numbering")
    status: StepStatus


class UpdatePlanObservation(Observation):
    step: int
    status: str

    def to_llm_text(self) -> str:
        return f"Step {self.step} marked {self.status}."


class UpdatePlanTool(Tool):
    name = "update_plan"
    description = (
        "Mark a step of the approved plan: `in_progress` before you start it, "
        "`done` once it is implemented and verified. Steps are numbered as in "
        "the plan (1-based)."
    )
    action_type = UpdatePlanAction
    observation_type = UpdatePlanObservation

    def execute(
        self, action: UpdatePlanAction, sandbox: Sandbox
    ) -> UpdatePlanObservation:
        # The plan itself lives on the conversation; the agent applies the
        # mutation when handling this tool, keeping tools conversation-agnostic.
        return UpdatePlanObservation(step=action.step, status=action.status)
