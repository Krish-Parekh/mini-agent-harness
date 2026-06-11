from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.api.deps import SkillsDep
from backend.schemas import SkillBody, SkillInfo

router = APIRouter()


@router.get("/skills", response_model=list[SkillInfo])
def list_skills(skills: SkillsDep):
    return [
        SkillInfo(name=r.name, description=r.description, scope=r.scope, repo=r.repo)
        for r in skills.all_skills()
    ]


# Query params (not path) because repo full names contain a slash.
@router.get("/skills/body", response_model=SkillBody)
def skill_body(name: str, skills: SkillsDep, repo: str | None = None):
    content = skills.read(name, repo)
    if content is None:
        raise HTTPException(status_code=404, detail="skill not found")
    return SkillBody(name=name, content=content)
