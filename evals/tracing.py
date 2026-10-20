from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from deepeval.dataset import Golden
from deepeval.test_case import ToolCall
from deepeval.tracing import observe, update_current_span, update_current_trace, update_llm_span

from backend.runtime.manager import _build_agent
from evals import SETTINGS
from miniagent.agent import Agent
from miniagent.confirm import ConfirmPolicy
from miniagent.conversation import Conversation
from miniagent.events import ActionEvent, CondensationEvent, ErrorEvent, Event, LLMUsageEvent, MessageEvent
from miniagent.llm import LLM
from miniagent.sandbox.local import LocalSandbox
from miniagent.text import clip

EVALS = Path(__file__).parent
REPOS = EVALS.parent / "data" / "repos" / "Krish-Parekh"
SPAN_CHARS = 1_500
CONTEXT_PREFIXES = ("<runtime-context>", "[workspace sketch]", "[repository instructions")


@dataclass
class Outcome:
    answer: str
    check_passed: bool
    check_detail: str


def _latest_turn(messages: list[dict]) -> str:
    turns = [m for m in messages if not str(m.get("content") or "").startswith(CONTEXT_PREFIXES)]
    return str(turns[-1].get("content") or "") if turns else ""


def _traced_complete(complete):
    @observe(type="llm")
    def traced(self, messages, tools=None, phase="agent"):
        response = complete(self, messages, tools, phase)
        calls = "\n".join(f"{c.name}({json.dumps(c.arguments)})" for c in response.tool_calls)
        update_llm_span(
            model=self.model,
            input_token_count=response.usage.prompt_tokens,
            output_token_count=response.usage.completion_tokens,
        )
        update_current_span(
            name=f"llm {phase}",
            input=clip(_latest_turn(messages), SPAN_CHARS),
            output=clip(f"{response.text or ''}\n{calls}".strip(), SPAN_CHARS),
        )
        return response

    return traced


def _traced_tool(run):
    @observe(type="tool")
    def traced(self, call, sandbox, conversation=None):
        result = run(self, call, sandbox, conversation)
        update_current_span(name=call.name, input=call.arguments, output=clip(result.content, SPAN_CHARS))
        return result

    return traced


def instrument() -> None:
    if getattr(LLM.complete, "_is_deepeval_observed", False):
        return
    LLM.complete = _traced_complete(LLM.complete)
    Agent._run_tool_for_observation = _traced_tool(Agent._run_tool_for_observation)


def _final_answer(events: list[Event]) -> str:
    for event in reversed(events):
        if isinstance(event, ActionEvent) and event.tool_name == "finish":
            return event.arguments.get("message", "")
        if isinstance(event, MessageEvent) and event.role == "assistant" and event.text.strip():
            return event.text
    return ""


def _check(meta: dict, workspace: Path) -> tuple[bool, str]:
    if "check" in meta:
        proc = subprocess.run(
            [sys.executable, str(EVALS / "checks" / meta["check"])],
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=60,
        )
        detail = (proc.stdout + proc.stderr).strip()[-500:]
        return proc.returncode == 0, detail or f"{meta['check']} passed"
    status = subprocess.run(["git", "status", "--porcelain"], cwd=workspace, capture_output=True, text=True)
    changed = status.stdout.strip()
    return not changed, f"files changed:\n{changed}" if changed else "no files changed"


@observe(type="agent")
def run_agent(golden: Golden) -> Outcome:
    meta = golden.additional_metadata
    cache = REPOS / meta["repo"]
    workspace = Path(tempfile.mkdtemp(prefix=f"eval-{golden.name}-"))
    subprocess.run(
        ["git", "-C", str(cache), "worktree", "add", "--detach", "--force", str(workspace), meta["commit"]],
        check=True,
        capture_output=True,
    )
    try:
        agent = _build_agent(SETTINGS, f"Krish-Parekh/{meta['repo']}", None)
        conversation = Conversation(
            agent=agent,
            sandbox=LocalSandbox(str(workspace)),
            confirm_policy=ConfirmPolicy("never"),
        )
        started = time.monotonic()
        conversation.send_message(golden.input)
        conversation.run()
        events = conversation.events
        usage = [e for e in events if isinstance(e, LLMUsageEvent)]
        errors = [e.message for e in events if isinstance(e, ErrorEvent)]
        answer = _final_answer(events)
        passed, detail = _check(meta, workspace)
        update_current_span(name="miniagent", input=golden.input, output=answer or "(no answer)")
        update_current_trace(
            name=golden.name,
            input=golden.input,
            output=answer or "(no answer)",
            tools_called=[
                ToolCall(name=e.tool_name, input_parameters=e.arguments)
                for e in events
                if isinstance(e, ActionEvent)
            ],
            metadata={
                "status": conversation.status.value,
                "error": errors[-1] if errors else None,
                "seconds": round(time.monotonic() - started, 1),
                "steps": sum(isinstance(e, ActionEvent) for e in events),
                "prompt_tokens": sum(u.prompt_tokens for u in usage),
                "cached_prompt_tokens": sum(u.cached_prompt_tokens for u in usage),
                "completion_tokens": sum(u.completion_tokens for u in usage),
                "cost_usd": round(sum(u.cost_usd for u in usage), 4),
                "compactions": sum(isinstance(e, CondensationEvent) for e in events),
            },
        )
        return Outcome(answer=answer, check_passed=passed, check_detail=detail)
    finally:
        subprocess.run(
            ["git", "-C", str(cache), "worktree", "remove", "--force", str(workspace)],
            capture_output=True,
        )
