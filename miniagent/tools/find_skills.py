from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from miniagent import skills_registry
from miniagent.sandbox.base import Sandbox
from miniagent.schema import Action, Observation
from miniagent.skills_registry import SkillHit
from miniagent.tools.base import Tool


class FindSkillsAction(Action):
    query: str = Field(description="What the skills should help with, e.g. 'react testing'.")


class FindSkillsObservation(Observation):
    query: str
    hits: list[SkillHit] = []
    error: bool = False
    message: str = ""

    def to_llm_text(self) -> str:
        if self.error:
            return f"ERROR: {self.message}"
        if not self.hits:
            return f"No skills on skills.sh match '{self.query}'."
        return "\n".join(
            f"- {hit.source}/{hit.skill_id} ({hit.installs} installs): "
            f"{hit.description}"
            for hit in self.hits
        )

    def ui_details(self) -> dict[str, Any] | None:
        return {
            "query": self.query,
            "hits": [hit.model_dump() for hit in self.hits],
        }


class FindSkillsTool(Tool):
    name = "find_skills"
    description = (
        "Search skills.sh for skills (reusable agent playbooks) matching a query. "
        "Returns each hit as source/skill_id with its install count and "
        "description. Follow up with `propose_skills`; never install skills yourself."
    )
    action_type = FindSkillsAction
    observation_type = FindSkillsObservation

    def execute(self, action: FindSkillsAction, sandbox: Sandbox) -> FindSkillsObservation:
        try:
            hits = skills_registry.search(action.query)
        except skills_registry.RegistryError as exc:
            return FindSkillsObservation(
                query=action.query, error=True, message=str(exc)
            )
        return FindSkillsObservation(query=action.query, hits=hits)


class ProposedSkill(BaseModel):
    source: str = Field(description="GitHub repo of the skill, e.g. 'vercel-labs/agent-skills'.")
    skill_id: str = Field(description="The skill id from find_skills.")
    name: str
    description: str = ""
    installs: int = 0


class ProposeSkillsAction(Action):
    skills: list[ProposedSkill] = Field(min_length=1, max_length=5)
    reason: str = Field(description="One sentence on why these skills fit the project.")


class ProposeSkillsObservation(Observation):
    def to_llm_text(self) -> str:
        return (
            "Proposed skills to the user. Stop here and wait; their reply says "
            "which they included."
        )


class ProposeSkillsTool(Tool):
    name = "propose_skills"
    description = (
        "Offer 1-5 skills from `find_skills` results to the user, who picks which "
        "to include in this project. Propose only genuinely relevant hits. "
        "Calling this pauses the turn until the user replies."
    )
    action_type = ProposeSkillsAction
    observation_type = ProposeSkillsObservation

    def execute(
        self, action: ProposeSkillsAction, sandbox: Sandbox
    ) -> ProposeSkillsObservation:
        return ProposeSkillsObservation()
