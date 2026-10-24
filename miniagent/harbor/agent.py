from __future__ import annotations

import asyncio
import threading
from importlib.metadata import version

from harbor.agents.base import BaseAgent
from harbor.agents.capabilities import AgentCapabilities
from harbor.agents.options import AgentOptions
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext
from harbor.models.trajectories import Agent as TrajectoryAgent
from harbor.models.trajectories import FinalMetrics
from harbor.utils.trajectory_utils import format_trajectory_json
from pydantic import Field

from miniagent.agent import TimeBudget
from miniagent.config import Settings, export_provider_keys
from miniagent.confirm import ConfirmPolicy
from miniagent.conversation import Conversation
from miniagent.events import Event, LLMUsageEvent
from miniagent.factory import build_agent
from miniagent.harbor.sandbox import HarborSandbox
from miniagent.harbor.trajectory import to_trajectory

_FIND_PACKAGE_MANAGER = (
    "for manager in apt-get dnf yum apk; do "
    'if command -v "$manager" >/dev/null 2>&1; then printf "%s" "$manager"; break; fi; '
    "done"
)
_INSTALL_TOOLS = {
    "apt-get": "apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y ripgrep tmux",
    "dnf": "dnf install -y ripgrep tmux",
    "yum": "yum install -y ripgrep tmux",
    "apk": "apk add --no-cache ripgrep tmux",
}


class MiniAgentOptions(AgentOptions):
    max_iterations: int = Field(default=200, description="Maximum agent steps.")
    timeout_sec: int | None = Field(
        default=None, description="Time budget the agent sees as elapsed / remaining each step."
    )


class MiniAgent(BaseAgent):
    capabilities = AgentCapabilities(atif=True)
    options_model = MiniAgentOptions
    options: MiniAgentOptions

    @staticmethod
    def name() -> str:
        return "miniagent"

    def version(self) -> str:
        return version("mini-agent")

    async def setup(self, environment: BaseEnvironment) -> None:
        present = await environment.exec(
            "command -v rg >/dev/null && command -v tmux >/dev/null", user="root"
        )
        if present.return_code != 0:
            found = await environment.exec(_FIND_PACKAGE_MANAGER, user="root")
            manager = (found.stdout or "").strip()
            if manager not in _INSTALL_TOOLS:
                raise RuntimeError("no apt-get, dnf, yum or apk to install ripgrep and tmux")
            installed = await environment.exec(_INSTALL_TOOLS[manager], user="root")
            if installed.return_code != 0:
                raise RuntimeError(
                    f"installing ripgrep and tmux failed: {installed.stdout}{installed.stderr}"
                )
        self._sandbox = await HarborSandbox.connect(environment)

    async def run(
        self, instruction: str, environment: BaseEnvironment, context: AgentContext
    ) -> None:
        settings = Settings(model=self.model_name) if self.model_name else Settings()
        export_provider_keys(settings)
        budget = TimeBudget(self.options.timeout_sec) if self.options.timeout_sec else None
        lock = threading.Lock()

        def record() -> None:
            with lock:
                self._record(conversation, settings.model, context)

        def on_event(event: Event) -> None:
            if isinstance(event, LLMUsageEvent):
                record()

        conversation = Conversation(
            agent=build_agent(settings, preset="headless", time_budget=budget),
            sandbox=self._sandbox,
            on_event=on_event,
            max_iterations=self.options.max_iterations,
            confirm_policy=ConfirmPolicy("never"),
        )
        conversation.send_message(instruction)
        try:
            await asyncio.to_thread(conversation.run)
        except asyncio.CancelledError:
            conversation.request_cancel()
            self._sandbox.close()
            await asyncio.to_thread(self._sandbox.kill_running)
            raise
        finally:
            record()

    def _record(self, conversation: Conversation, model: str, context: AgentContext) -> None:
        usage = [e for e in conversation.events if isinstance(e, LLMUsageEvent)]
        context.n_input_tokens = sum(e.prompt_tokens for e in usage)
        context.n_cache_tokens = sum(e.cached_prompt_tokens for e in usage)
        context.n_output_tokens = sum(e.completion_tokens for e in usage)
        context.cost_usd = sum(e.cost_usd for e in usage)
        trajectory = to_trajectory(
            conversation.events,
            session_id=conversation.id,
            agent=TrajectoryAgent(name=self.name(), version=self.version(), model_name=model),
            final_metrics=FinalMetrics(
                total_prompt_tokens=context.n_input_tokens,
                total_completion_tokens=context.n_output_tokens,
                total_cached_tokens=context.n_cache_tokens,
                total_cost_usd=context.cost_usd,
            ),
        )
        (self.logs_dir / "trajectory.json").write_text(
            format_trajectory_json(trajectory.to_json_dict())
        )
