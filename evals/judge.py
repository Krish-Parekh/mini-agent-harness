from __future__ import annotations

import asyncio

from deepeval.models import DeepEvalBaseLLM
from pydantic import BaseModel

from miniagent.llm import LLM


class LLMJudge(DeepEvalBaseLLM):
    def __init__(self, model: str) -> None:
        self.llm = LLM(model=model, max_tokens=4096)
        super().__init__(model)

    def load_model(self) -> LLM:
        return self.llm

    def generate(self, prompt: str, schema: type[BaseModel] | None = None):
        messages = [{"role": "user", "content": prompt}]
        if schema is not None:
            return self.llm.complete_structured(messages, schema, phase="judge")
        return self.llm.complete(messages, phase="judge").text or ""

    async def a_generate(self, prompt: str, schema: type[BaseModel] | None = None):
        return await asyncio.to_thread(self.generate, prompt, schema)

    def get_model_name(self) -> str:
        return self.llm.model
