from __future__ import annotations

from pydantic import BaseModel, Field

from miniagent.sandbox.base import Sandbox
from miniagent.schema import Action, Observation
from miniagent.tools.base import Tool


class Question(BaseModel):
    question: str = Field(description="The full question to ask the user.")
    header: str = Field(
        default="",
        description="A short label for the question (a few words), shown as a heading.",
    )
    options: list[str] = Field(
        min_length=2,
        description="The choices to offer. The user may also reply with their own answer.",
    )
    multi_select: bool = Field(
        default=False,
        description="Whether the user may pick more than one option.",
    )


class AskUserAction(Action):
    questions: list[Question] = Field(min_length=1, max_length=4)


class AskUserObservation(Observation):
    questions: list[Question]

    def to_llm_text(self) -> str:
        lines = ["Asked the user:"]
        for q in self.questions:
            lines.append(f"- {q.question} (options: {', '.join(q.options)})")
        lines.append(
            "Stop here and wait for the user's answers, which arrive as their next message."
        )
        return "\n".join(lines)


class AskUserTool(Tool):
    name = "ask_user"
    description = (
        "Ask the user one to four multiple-choice questions to clarify ambiguous "
        "requirements before you act. Provide each question's text, a short header, "
        "and 2+ options; set multi_select when several answers are valid. Prefer this "
        "over guessing when the task could reasonably go more than one way. Calling "
        "this pauses the turn until the user answers."
    )
    action_type = AskUserAction
    observation_type = AskUserObservation

    def execute(self, action: AskUserAction, sandbox: Sandbox) -> AskUserObservation:
        return AskUserObservation(questions=action.questions)
