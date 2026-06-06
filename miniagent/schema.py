from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class Action(BaseModel):
    model_config = ConfigDict(frozen=True)


class Observation(BaseModel):
    model_config = ConfigDict(frozen=True)

    def to_llm_text(self) -> str:
        raise NotImplementedError(f"{type(self).__name__} must implement to_llm_text()")
