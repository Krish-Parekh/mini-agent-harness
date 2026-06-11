from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict

from miniagent.llm import LLM

RiskLevel = Literal["safe", "mutating", "dangerous", "unknown"]


class CommandPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)

    risk: RiskLevel = "unknown"
    read_only: bool = False
    is_verification: bool = False
    verification_unavailable: bool = False
    reason: str = ""

    @property
    def mutates_workspace(self) -> bool:
        return self.risk in ("mutating", "dangerous")

    @property
    def needs_confirmation(self) -> bool:
        return self.risk == "dangerous"


class PolicyProvider(Protocol):
    def classify_bash(self, command: str) -> CommandPolicy: ...

    def classify_finish_message(self, message: str) -> CommandPolicy: ...


_BASH_POLICY_SYSTEM = """You classify shell commands for a coding agent.

Return a structured response with risk, read_only, is_verification,
verification_unavailable, and a short reason.

Definitions:
- "safe": command only reads or inspects local state.
- "mutating": command changes workspace files, dependencies, git state, or external state.
- "dangerous": command can destroy data, discard user work, force push, write raw devices,
  shut down/reboot, or otherwise has hard-to-reverse effects.
- read_only is true only when the command does not mutate anything.
- is_verification is true for tests, lint, typecheck, build, compile, or focused checks.

If uncertain, use risk="unknown", read_only=false, and is_verification=false.
"""

_FINISH_POLICY_SYSTEM = """You classify a coding agent's final message.

Return a structured response with risk="safe", read_only=true,
is_verification=false, verification_unavailable, and a short reason.

verification_unavailable is true only when the message clearly says verification,
tests, checks, build, lint, typecheck, or compile could not be run and gives a reason.
"""


class PolicyClassifier:
    def __init__(self, llm: LLM) -> None:
        self.llm = llm
        self._bash_cache: dict[str, CommandPolicy] = {}
        self._finish_cache: dict[str, CommandPolicy] = {}

    def classify_bash(self, command: str) -> CommandPolicy:
        cached = self._bash_cache.get(command)
        if cached is not None:
            return cached
        policy = self._classify(
            _BASH_POLICY_SYSTEM,
            f"Command:\n{command}",
            fallback=CommandPolicy(
                risk="unknown",
                read_only=False,
                is_verification=False,
                reason="policy classifier failed closed",
            ),
        )
        self._bash_cache[command] = policy
        return policy

    def classify_finish_message(self, message: str) -> CommandPolicy:
        cached = self._finish_cache.get(message)
        if cached is not None:
            return cached
        policy = self._classify(
            _FINISH_POLICY_SYSTEM,
            f"Final message:\n{message}",
            fallback=CommandPolicy(
                risk="safe",
                read_only=True,
                verification_unavailable=False,
                reason="policy classifier failed closed",
            ),
        )
        self._finish_cache[message] = policy
        return policy

    def _classify(
        self, system: str, user: str, fallback: CommandPolicy
    ) -> CommandPolicy:
        try:
            return self.llm.complete_structured(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                CommandPolicy,
            )
        except Exception:
            return fallback
