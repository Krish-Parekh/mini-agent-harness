from __future__ import annotations

from miniagent.sandbox.base import Sandbox
from miniagent.schema import Action, Observation
from miniagent.skills import SkillLibrary
from miniagent.tools.base import Tool


class ReadSkillAction(Action):
    name: str


class ReadSkillObservation(Observation):
    content: str
    error: bool = False

    def to_llm_text(self) -> str:
        return self.content


class ReadSkillTool(Tool):
    name = "read_skill"
    description = (
        "Read the full body of a skill listed in the Skills section of your "
        "context. Pass the skill's name exactly as it appears in the list."
    )
    action_type = ReadSkillAction
    observation_type = ReadSkillObservation

    def __init__(self, library: SkillLibrary, repo: str | None) -> None:
        self._library = library
        self._repo = repo

    # Skills are server-side knowledge, not workspace files; sandbox is unused
    # (same as finish).
    def execute(self, action: ReadSkillAction, sandbox: Sandbox) -> ReadSkillObservation:
        content = self._library.read(action.name, self._repo)
        if content is None:
            available = ", ".join(r.name for r in self._library.index(self._repo))
            return ReadSkillObservation(
                content=f"Unknown skill: {action.name}. Available: {available or 'none'}.",
                error=True,
            )
        return ReadSkillObservation(content=content)
