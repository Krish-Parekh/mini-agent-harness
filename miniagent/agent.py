from __future__ import annotations

import dataclasses
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, TypeAlias

import logfire
from pydantic import ValidationError

from miniagent.classification import TaskClassifier, TaskRoute, TaskRouteProvider
from miniagent.events import (
    ActionEvent,
    CondensationEvent,
    ErrorEvent,
    Event,
    LLMUsageEvent,
    MessageEvent,
    ObservationEvent,
    RepoInstructionsEvent,
    WorkspaceSketchEvent,
)
from miniagent.llm import LLM, ContextOverflow, LLMResponse, ToolCall
from miniagent.policy import BashContext, PolicyClassifier, PolicyProvider
from miniagent.prompts import (
    CONDENSE_SYSTEM_PROMPT,
    DEFAULT_SYSTEM_PROMPT,
    EARLY_STOP_PROMPT,
    IMPLEMENT_PLAN_DIRECTIVE,
    PLAN_MODE_DIRECTIVE,
    ROUTE_CODE_EDIT_DIRECTIVE,
    ROUTE_PR_FLOW_DIRECTIVE,
    ROUTE_QUESTION_DIRECTIVE,
    ROUTE_REVIEW_DIRECTIVE,
)
from miniagent.sandbox.base import SandboxError
from miniagent.text import clip
from miniagent.tools.base import ToolRegistry
from miniagent.tracing import bind_context, tool_attributes, tool_result_attributes
from miniagent.tools.mcp import NAME_PREFIX as MCP_PREFIX, McpTool
from miniagent.tools.plan import Plan

if TYPE_CHECKING:
    from miniagent.conversation import Conversation
    from miniagent.sandbox.base import Sandbox

ToolOutcome: TypeAlias = Literal["ok", "finished", "paused"]

# Per-message ceiling sent to the LLM; long tool output is head+tail clipped.
_MAX_MESSAGE_CHARS = 12_000

# A weak model can get wedged re-issuing one identical call. Nudge it in the
# observation so the model course-corrects before the conversation-level
# stuck detector pauses the run.
_NUDGE_AFTER_REPEATS = 2

_MAX_FILE_SKETCH_CHARS = 2_000

COMPACT_AT = 0.8
PRUNE_TARGET = 0.6
RETAIN_SHARE = 0.16
ELIDE_ABOVE_CHARS = 4_000
ELIDE_HEAD_CHARS = 1_500
ELIDE_TAIL_CHARS = 1_000
_MIN_CONDENSE_EVENTS = 12
_MAX_FAILURE_EVIDENCE_CHARS = 8_000
_MAX_FAILURE_ITEM_CHARS = 1_000


_log = logging.getLogger(__name__)

REPO_INSTRUCTION_FILES = ("AGENTS.md", "CLAUDE.md")
REPO_INSTRUCTIONS_MAX_CHARS = 8_000
SPILL_THRESHOLD_CHARS = 12_000
SPILL_PREVIEW_CHARS = 6_000
SPILL_ROOT = ".miniagent"
SPILL_DIR = f"{SPILL_ROOT}/outputs"


@dataclass(frozen=True)
class ToolResult:
    content: str
    error: bool
    duration_ms: int | None = None
    details: dict | None = None


def _file_sketch(sandbox: Sandbox) -> str:
    """Tracked-files listing so the model can orient before exploring."""
    result = sandbox.run_command("git ls-files", timeout=10)
    files = result.stdout.strip()
    if result.exit_code == 0 and files:
        return "\n\n## Tracked files (git ls-files)\n" + clip(
            files, _MAX_FILE_SKETCH_CHARS
        )
    try:
        has_git_dir = ".git" in sandbox.list_files(".")
    except Exception:
        has_git_dir = False
    if not has_git_dir:
        return ""
    workspace = Path(sandbox.workspace_dir)
    fallback = sorted(
        str(path.relative_to(workspace))
        for path in workspace.rglob("*")
        if path.is_file()
        and not any(part.startswith(".") for part in path.relative_to(workspace).parts)
    )
    if not fallback:
        return ""
    return "\n\n## Tracked files (git ls-files)\n" + clip(
        "\n".join(fallback), _MAX_FILE_SKETCH_CHARS
    )


def _pruned_output(event: ObservationEvent) -> str:
    details = event.details or {}
    total = details.get("full_chars", len(event.content))
    spill = details.get("spill_path")
    where = f"Full output: {spill}" if spill else "Re-run the call for the full output"
    return (
        f"{event.content[:ELIDE_HEAD_CHARS]}\n"
        f"[old tool output: {total:,} chars, middle pruned. {where}]\n"
        f"{event.content[-ELIDE_TAIL_CHARS:]}"
    )


def _spill_oversized(call: ToolCall, result: ToolResult, sandbox: Sandbox) -> ToolResult:
    content = result.content
    if len(content) <= SPILL_THRESHOLD_CHARS:
        return result
    path = f"{SPILL_DIR}/{call.id}.txt"
    try:
        with logfire.span("tool.spill", path=path, chars=len(content)):
            _exclude_from_git(sandbox)
            sandbox.write_file(path, content)
    except Exception as exc:
        _log.warning("could not spill %s output: %s", call.name, exc)
        return dataclasses.replace(
            result,
            content=clip(content, SPILL_PREVIEW_CHARS) + "\n[full output unavailable]",
        )
    note = (
        f"\n[output truncated: {len(content):,} chars total. Full output: {path}. "
        "Use file_edit view with view_range, or bash grep/sed, to read the rest]"
    )
    details = {**(result.details or {}), "spill_path": path, "full_chars": len(content)}
    return dataclasses.replace(
        result, content=clip(content, SPILL_PREVIEW_CHARS) + note, details=details
    )


def _exclude_from_git(sandbox: Sandbox) -> None:
    sandbox.run_command(
        'p="$(git rev-parse --git-path info/exclude 2>/dev/null)" && '
        'mkdir -p "$(dirname "$p")" && '
        f'(grep -qxF "{SPILL_ROOT}/" "$p" 2>/dev/null || echo "{SPILL_ROOT}/" >> "$p")',
        timeout=15,
    )


def _pair_tool_calls(messages: list[dict]) -> list[dict]:
    repaired: list[dict] = []
    index = 0
    while index < len(messages):
        message = messages[index]
        repaired.append(message)
        index += 1
        call_ids = [c["id"] for c in message.get("tool_calls") or []]
        if message.get("role") != "assistant" or not call_ids:
            continue
        answered: set[str] = set()
        while index < len(messages) and messages[index].get("role") == "tool":
            answered.add(messages[index].get("tool_call_id"))
            repaired.append(messages[index])
            index += 1
        for call_id in call_ids:
            if call_id in answered:
                continue
            _log.warning("tool call %s had no result; closing it", call_id)
            repaired.append(
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": "Not executed. Re-issue the call if it is still needed.",
                }
            )
    return repaired


class Agent:
    def __init__(
        self,
        llm: LLM,
        tools: ToolRegistry,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        repo: str | None = None,
        branch: str | None = None,
        policy: PolicyProvider | None = None,
        task_router: TaskRouteProvider | None = None,
    ) -> None:
        self.llm = llm
        self.tools = tools
        self.system_prompt = system_prompt
        self.repo = repo
        self.branch = branch
        self.policy = policy or PolicyClassifier(llm)
        self.task_router = task_router or TaskClassifier(llm)
        self.skills_block = ""
        self.mcp_instructions: dict[str, str] = {}

    def classify_task_route(self, text: str, plan_mode: bool = False) -> TaskRoute:
        if plan_mode:
            return TaskRoute.PLAN
        return self.task_router.classify_task_route(text)

    def step(self, conversation: Conversation, sandbox: Sandbox) -> None:
        with logfire.span(
            "agent.step",
            conversation_id=conversation.id,
            agent_model=self.llm.model,
            **{"langfuse.observation.type": "span"},
        ):
            self._step(conversation, sandbox)

    def _bind_policy_context(
        self, conversation: Conversation, sandbox: Sandbox
    ) -> None:
        bind = getattr(self.policy, "bind_context", None)
        if bind is None:
            return

        def context() -> BashContext:
            recent = [
                e.text
                for e in conversation.events
                if isinstance(e, MessageEvent) and e.role == "user"
            ][-3:]
            return BashContext(
                cwd=sandbox.workspace_dir,
                repo=self.repo,
                recent_user_messages=tuple(recent),
            )

        bind(context)

    def _step(self, conversation: Conversation, sandbox: Sandbox) -> None:
        self._bind_policy_context(conversation, sandbox)
        pending = conversation.pending_action()
        if pending is not None:
            self._run_tool(
                ToolCall(
                    id=pending.tool_call_id,
                    name=pending.tool_name,
                    arguments=pending.arguments,
                ),
                conversation,
                sandbox,
            )
            return

        self._ensure_workspace_sketch(conversation, sandbox)
        self._ensure_repo_instructions(conversation, sandbox)
        self._maybe_condense(conversation, sandbox)
        try:
            response = self._complete_step(conversation, sandbox)
        except ContextOverflow:
            if not self._maybe_condense(conversation, sandbox, trigger="overflow"):
                raise
            try:
                response = self._complete_step(conversation, sandbox)
            except ContextOverflow:
                conversation.add_event(
                    ErrorEvent(message="Context window exceeded after compaction")
                )
                conversation.set_error()
                return
        self._record_llm_usage(conversation, response, "step")

        if response.text:
            conversation.add_event(MessageEvent(role="assistant", text=response.text))

        if response.tool_calls:
            actions = self._record_tool_calls(response.tool_calls, conversation)
            self._execute_actions(actions, conversation, sandbox)
            return

        # No tool call ends the turn; re-prompting here would loop to the cap.
        if not response.text:
            conversation.add_event(ErrorEvent(message="empty model response"))
            conversation.set_error()
            return
        conversation.set_idle()

    def _complete_step(
        self, conversation: Conversation, sandbox: Sandbox
    ) -> LLMResponse:
        messages = self._build_messages(conversation, sandbox)
        return self.llm.complete(messages, self.tools.all(), phase="step")

    def early_stop(self, conversation: Conversation, sandbox: Sandbox) -> bool:
        """Generate a best-effort final response after the loop hits its cap."""
        self._maybe_condense(conversation, sandbox)
        messages = self._build_messages(conversation, sandbox)
        messages.append({"role": "user", "content": EARLY_STOP_PROMPT})
        response = self.llm.complete(messages, phase="early_stop")
        self._record_llm_usage(conversation, response, "early_stop")
        text = (response.text or "").strip()
        if not text:
            conversation.add_event(ErrorEvent(message="empty early-stop response"))
            conversation.set_error()
            return False
        conversation.add_event(MessageEvent(role="assistant", text=text))
        conversation.set_idle()
        return True

    def _context_block(self, conversation: Conversation, sandbox: Sandbox) -> str:
        """Workspace context appended to the system prompt every turn.

        Kept intentionally small. Larger orientation data, like the tracked-file
        sketch, is added once to the conversation history instead of repeated on
        every agent step.
        """
        lines = ["\n\n# Workspace"]
        if self.repo:
            branch = f" (branch: {self.branch})" if self.branch else ""
            lines.append(f"- repository: {self.repo}{branch}")
        lines.append(f"- working directory: {sandbox.workspace_dir}")
        lines.append("Relative paths resolve against the working directory.")
        lines.append(
            "Repository instructions (AGENTS.md / CLAUDE.md), when present, "
            "override general style guidance but never the safety rules."
        )
        lines.append(
            "Each step ends with a <runtime-context> message from MiniAgent "
            "carrying the current mode, routing hints and enabled skills."
        )
        return "\n".join(lines)

    @staticmethod
    def _has_workspace_sketch(conversation: Conversation) -> bool:
        return any(
            isinstance(event, WorkspaceSketchEvent) for event in conversation.events
        )

    def _ensure_repo_instructions(
        self, conversation: Conversation, sandbox: Sandbox
    ) -> None:
        if any(isinstance(e, RepoInstructionsEvent) for e in conversation.events):
            return
        paths: list[str] = []
        parts: list[str] = []
        for name in REPO_INSTRUCTION_FILES:
            try:
                text = sandbox.read_file(name).strip()
            except Exception:
                continue
            if text:
                paths.append(name)
                parts.append(f"# {name}\n{text}")
        if not paths:
            return
        content = "\n\n".join(parts)
        truncated = len(content) > REPO_INSTRUCTIONS_MAX_CHARS
        if truncated:
            content = content[:REPO_INSTRUCTIONS_MAX_CHARS] + "\n[truncated]"
        conversation.add_event(
            RepoInstructionsEvent(paths=paths, content=content, truncated=truncated)
        )

    def _ensure_workspace_sketch(
        self, conversation: Conversation, sandbox: Sandbox
    ) -> None:
        if self._has_workspace_sketch(conversation):
            return
        sketch = _file_sketch(sandbox).strip()
        if sketch:
            conversation.add_event(WorkspaceSketchEvent(content=sketch))

    def _route_block(self, conversation: Conversation) -> str:
        if conversation.route == TaskRoute.QUESTION:
            return "\n\n" + ROUTE_QUESTION_DIRECTIVE
        if conversation.route == TaskRoute.CODE_EDIT:
            return "\n\n" + ROUTE_CODE_EDIT_DIRECTIVE
        if conversation.route == TaskRoute.REVIEW:
            return "\n\n" + ROUTE_REVIEW_DIRECTIVE
        if conversation.route == TaskRoute.PR_FLOW:
            return "\n\n" + ROUTE_PR_FLOW_DIRECTIVE
        return ""

    def _maybe_condense(
        self,
        conversation: Conversation,
        sandbox: Sandbox,
        trigger: Literal["threshold", "overflow"] = "threshold",
    ) -> bool:
        window = self.llm.context_window()
        tokens = self._prompt_tokens(conversation, sandbox)
        if trigger == "overflow":
            window = min(window, max(tokens, 1))
        elif tokens < COMPACT_AT * window:
            return False
        with logfire.span(
            "agent.compact", trigger=trigger, tokens_before=tokens, window=window
        ) as span:
            if self._elide_old_outputs(conversation, sandbox, window, trigger):
                span.set_attribute("pruned_only", True)
                compacted = True
            else:
                compacted = self._summarize(conversation, sandbox, window, trigger)
                span.set_attribute("pruned_only", False)
                span.set_attribute("summarized", compacted)
            span.set_attribute(
                "tokens_after", self._prompt_tokens(conversation, sandbox)
            )
            return compacted

    def _prompt_tokens(self, conversation: Conversation, sandbox: Sandbox) -> int:
        messages = self._build_messages(conversation, sandbox)
        tokens = self.llm.count_tokens(messages, self.tools.all())
        if tokens:
            return tokens
        return sum(len(str(m.get("content") or "")) for m in messages) // 4

    def _elide_old_outputs(
        self,
        conversation: Conversation,
        sandbox: Sandbox,
        window: int,
        trigger: str,
    ) -> bool:
        candidates = conversation.condensation_candidates(
            retain_chars=int(RETAIN_SHARE * window * 4)
        )
        already = conversation.elided_event_ids()
        target = PRUNE_TARGET * window
        tokens = self._prompt_tokens(conversation, sandbox)
        chosen: list[str] = []
        for event in candidates:
            if tokens < target:
                break
            if (
                isinstance(event, ObservationEvent)
                and event.id not in already
                and len(event.content) > ELIDE_ABOVE_CHARS
            ):
                chosen.append(event.id)
                tokens -= (len(event.content) - len(_pruned_output(event))) // 4
        if not chosen or tokens >= target:
            return False
        conversation.add_event(
            CondensationEvent(
                summary="",
                replaced_event_ids=[],
                elided_event_ids=chosen,
                trigger=trigger,
                pruned_only=True,
            )
        )
        return True

    def _summarize(
        self,
        conversation: Conversation,
        sandbox: Sandbox,
        window: int,
        trigger: str,
    ) -> bool:
        candidates = conversation.condensation_candidates(
            retain_chars=int(RETAIN_SHARE * window * 4)
        )
        if len(candidates) < _MIN_CONDENSE_EVENTS:
            return False
        messages = self._build_messages(conversation, sandbox)
        messages.append({"role": "user", "content": CONDENSE_SYSTEM_PROMPT})
        response = self.llm.complete(messages, self.tools.all(), phase="condense")
        self._record_llm_usage(conversation, response, "condense")
        summary = (response.text or "").strip()
        if not summary:
            return False
        failure_evidence = self._failure_evidence(candidates)
        if failure_evidence:
            summary += "\n\nFailure/error evidence to preserve:\n" + failure_evidence
        conversation.add_event(
            CondensationEvent(
                summary=summary,
                replaced_event_ids=[event.id for event in candidates],
                trigger=trigger,
            )
        )
        return True

    @staticmethod
    def _failure_evidence(events: list[Event]) -> str:
        lines: list[str] = []
        for event in events:
            if isinstance(event, ObservationEvent) and event.error:
                lines.append(
                    f"- failed {event.tool_name}: "
                    + clip(event.content, _MAX_FAILURE_ITEM_CHARS)
                )
            elif isinstance(event, ErrorEvent):
                lines.append(
                    "- error: " + clip(event.message, _MAX_FAILURE_ITEM_CHARS)
                )
        return clip("\n".join(lines), _MAX_FAILURE_EVIDENCE_CHARS)

    def _build_messages(
        self, conversation: Conversation, sandbox: Sandbox
    ) -> list[dict]:
        system_prompt = self.system_prompt + self._context_block(conversation, sandbox)
        messages: list[dict] = [{"role": "system", "content": system_prompt}]
        compacted = conversation.compacted_event_ids()
        elided = conversation.elided_event_ids()
        for event in conversation.events:
            if isinstance(event, CondensationEvent):
                summary = event.to_chat_message()
                if summary is not None:
                    messages.append(summary)
        pending: dict | None = None  # assistant turn being assembled

        def flush() -> None:
            nonlocal pending
            if pending is not None:
                messages.append(pending)
                pending = None

        for event in conversation.events:
            if isinstance(event, CondensationEvent) or event.id in compacted:
                continue
            # An assistant turn's text and its tool calls arrive as separate
            # events, but the LLM expects ONE assistant message carrying both
            # `content` and `tool_calls`, with parallel calls sharing that single
            # message. Emitting them as separate assistant messages produces a
            # malformed history that the next completion rejects, so coalesce here.
            if isinstance(event, MessageEvent) and event.role == "assistant":
                if pending is None:
                    pending = {"role": "assistant", "content": None}
                pending["content"] = clip(event.text, _MAX_MESSAGE_CHARS)
                continue
            if isinstance(event, ActionEvent):
                if pending is None:
                    pending = {"role": "assistant", "content": None}
                pending.setdefault("tool_calls", []).append(
                    {
                        "id": event.tool_call_id,
                        "type": "function",
                        "function": {
                            "name": event.tool_name,
                            "arguments": event.raw_arguments
                            if event.raw_arguments is not None
                            else json.dumps(event.arguments),
                        },
                    }
                )
                continue

            # Any other event ends the assistant turn; flush it first so order is
            # preserved (assistant turn, then its tool observations).
            flush()
            message = event.to_chat_message()
            if message is None:
                continue
            if event.id in elided and isinstance(event, ObservationEvent):
                message = {**message, "content": _pruned_output(event)}
            # Clip oversized content so one giant observation can't exhaust the
            # context window; truncating (not dropping events) keeps tool_call
            # pairing intact, and clipping at send-time also rescues stored events.
            content = message.get("content")
            if isinstance(content, str):
                message = {**message, "content": clip(content, _MAX_MESSAGE_CHARS)}
            messages.append(message)

        flush()
        messages = _pair_tool_calls(messages)
        messages.append(
            {"role": "user", "content": self._runtime_context(conversation)}
        )
        return messages

    def _runtime_context(self, conversation: Conversation) -> str:
        sections = [
            "Runtime context for this step, set by MiniAgent rather than typed by "
            "the user. It reflects the current mode and enabled extensions."
        ]
        route = self._route_block(conversation).strip()
        if route:
            sections.append(route)
        if conversation.plan_mode:
            sections.append(PLAN_MODE_DIRECTIVE.strip())
        elif conversation.implementing_plan:
            sections.append(IMPLEMENT_PLAN_DIRECTIVE.strip())
        if self.skills_block:
            sections.append(
                "# Skills\nPlaybooks the user enabled for this conversation. "
                "Before a task one applies to, load it with the `skill` tool and "
                "follow it.\n" + self.skills_block
            )
        for server, instructions in sorted(self.mcp_instructions.items()):
            sections.append(f"# MCP server: {server}\n{instructions}")
        body = "\n\n".join(sections)
        return f"<runtime-context>\n{body}\n</runtime-context>"

    def _record_llm_usage(
        self, conversation: Conversation, response: LLMResponse, phase: str
    ) -> None:
        usage = response.usage
        if not usage.total_tokens and not response.cost:
            return
        conversation.add_event(
            LLMUsageEvent(
                phase=phase,
                model=self.llm.model,
                prompt_tokens=usage.prompt_tokens,
                completion_tokens=usage.completion_tokens,
                total_tokens=usage.total_tokens,
                cached_prompt_tokens=usage.cached_prompt_tokens,
                cache_creation_tokens=usage.cache_creation_tokens,
                cost_usd=response.cost,
            )
        )

    def _record_tool_calls(
        self, calls: list[ToolCall], conversation: Conversation
    ) -> list[ActionEvent]:
        actions: list[ActionEvent] = []
        for call in calls:
            action = ActionEvent(
                tool_name=call.name,
                arguments=call.arguments,
                tool_call_id=call.id,
                raw_arguments=call.raw_arguments,
                parse_error=call.parse_error,
            )
            conversation.add_event(action)
            actions.append(action)
        return actions

    def _execute_actions(
        self,
        actions: list[ActionEvent],
        conversation: Conversation,
        sandbox: Sandbox,
    ) -> None:
        index = 0
        while index < len(actions):
            group = self._parallel_safe_group(actions, index, conversation)
            if group:
                self._execute_parallel_group(group, conversation, sandbox)
                index += len(group)
                continue

            outcome = self._execute_action(
                actions[index], conversation, sandbox, batch=actions
            )
            if outcome == "paused":
                self._skip_later_actions(
                    actions[index + 1 :],
                    conversation,
                    "Skipped because an earlier tool call paused; reissue this call if it is still needed.",
                )
                break
            if outcome == "finished":
                self._skip_later_actions(
                    actions[index + 1 :],
                    conversation,
                    "Skipped because an earlier tool call ended the turn; reissue this call if it is still needed.",
                )
                break
            index += 1

    def _parallel_safe_group(
        self,
        actions: list[ActionEvent],
        start: int,
        conversation: Conversation,
    ) -> list[ActionEvent]:
        group: list[ActionEvent] = []
        for action in actions[start:]:
            if not self._is_parallel_safe(action, conversation):
                break
            group.append(action)
        return group if len(group) > 1 else []

    def _is_parallel_safe(
        self, action_event: ActionEvent, conversation: Conversation
    ) -> bool:
        if getattr(action_event, "parse_error", None) is not None:
            return False
        if self._needs_confirmation(action_event, conversation):
            return False
        if conversation.plan_mode and self._blocked_in_plan_mode(action_event):
            return False
        if action_event.tool_name == "file_edit":
            return action_event.arguments.get("command") == "view"
        if action_event.tool_name in ("web_search", "fetch_url"):
            return True
        if action_event.tool_name == "bash":
            return self.policy.classify_bash(
                action_event.arguments.get("command", "")
            ).read_only
        return False

    def _execute_parallel_group(
        self,
        actions: list[ActionEvent],
        conversation: Conversation,
        sandbox: Sandbox,
    ) -> None:
        calls = [
            ToolCall(
                id=action.tool_call_id,
                name=action.tool_name,
                arguments=action.arguments,
                raw_arguments=action.raw_arguments,
                parse_error=action.parse_error,
            )
            for action in actions
        ]
        with ThreadPoolExecutor(max_workers=len(calls)) as executor:
            futures = [
                executor.submit(bind_context(self._run_tool_for_observation), call, sandbox)
                for call in calls
            ]
            results = [future.result() for future in futures]
        for call, result in zip(calls, results):
            self._observe(
                conversation,
                call,
                result.content,
                result.error,
                result.duration_ms,
                result.details,
            )

    def _execute_action(
        self,
        action_event: ActionEvent,
        conversation: Conversation,
        sandbox: Sandbox,
        *,
        batch: list[ActionEvent] | None = None,
    ) -> ToolOutcome:
        batch = batch or [action_event]
        call = ToolCall(
            id=action_event.tool_call_id,
            name=action_event.tool_name,
            arguments=action_event.arguments,
            raw_arguments=action_event.raw_arguments,
            parse_error=action_event.parse_error,
        )

        parse_error = getattr(call, "parse_error", None)
        if parse_error is not None:
            self._observe(
                conversation,
                call,
                f"Invalid JSON arguments for {call.name}: {parse_error}",
                True,
            )
            return "ok"

        if conversation.plan_mode and self._blocked_in_plan_mode(action_event):
            self._observe(
                conversation,
                call,
                "Plan mode is active; this action would modify the workspace. "
                "Explore read-only and call `present_plan` when ready.",
                True,
            )
            return "ok"

        if self._needs_confirmation(action_event, conversation):
            conversation.set_waiting_for_confirmation()
            return "paused"

        finished = self._run_tool(
            call, conversation, sandbox, batch_size=len(batch)
        )
        return "finished" if finished else "ok"

    @staticmethod
    def _skip_later_actions(
        actions: list[ActionEvent], conversation: Conversation, reason: str
    ) -> None:
        for action in actions:
            Agent._observe(
                conversation,
                ToolCall(
                    id=action.tool_call_id,
                    name=action.tool_name,
                    arguments=action.arguments,
                    raw_arguments=action.raw_arguments,
                    parse_error=action.parse_error,
                ),
                reason,
                True,
            )

    def _run_tool(
        self,
        call: ToolCall,
        conversation: Conversation,
        sandbox: Sandbox,
        *,
        batch_size: int = 1,
    ) -> bool:
        if call.name == "finish" and batch_size > 1:
            self._observe(
                conversation,
                call,
                "Cannot call `finish` together with other tools in the same "
                "step. Review the tool results above, then call `finish` "
                "alone with your summary.",
                True,
            )
            return False

        result = self._run_tool_for_observation(call, sandbox, conversation)
        self._observe(
            conversation,
            call,
            result.content,
            result.error,
            result.duration_ms,
            result.details,
        )
        if result.error:
            return False

        if call.name == "finish":
            conversation.implementing_plan = False
            conversation.set_finished()
            return True
        if call.name == "present_plan":
            action = self.tools[call.name].action_type(**call.arguments)
            # Plan delivered: stay in plan mode so a reply refines the plan
            # (read-only); only the user's explicit approval starts implementing.
            conversation.plan = Plan(
                title=action.title,
                steps=[step.model_copy() for step in action.steps],
            )
            conversation.implementing_plan = False
            conversation.set_idle()
            return True
        if call.name == "ask_user":
            # Soft pause for the user's answer; stay in plan mode if we were in it
            # so the planning flow resumes after they reply.
            conversation.set_idle()
            return True
        return False

    def _run_tool_for_observation(
        self,
        call: ToolCall,
        sandbox: Sandbox,
        conversation: Conversation | None = None,
    ) -> ToolResult:
        with logfire.span(
            "tool.execute {tool}",
            tool=call.name,
            tool_call_id=call.id,
            cwd=getattr(sandbox, "working_dir", None),
        ) as span:
            span.set_attributes(tool_attributes(name=call.name, arguments=call.arguments))
            result = _spill_oversized(
                call, self._execute_tool_call(call, sandbox, conversation), sandbox
            )
            span.set_attributes(
                tool_result_attributes(
                    content=result.content, error=result.error, details=result.details
                )
            )
            if result.duration_ms is not None:
                span.set_attribute("tool.duration_ms", result.duration_ms)
        return result

    def _execute_tool_call(
        self,
        call: ToolCall,
        sandbox: Sandbox,
        conversation: Conversation | None = None,
    ) -> ToolResult:
        if call.name not in self.tools:
            available = ", ".join(t.name for t in self.tools.all())
            return ToolResult(f"Unknown tool: {call.name}. Available: {available}", True)

        tool = self.tools[call.name]
        try:
            action = tool.action_type(**call.arguments)
        except ValidationError as exc:
            return ToolResult(f"Invalid arguments: {exc}", True)

        if (
            call.name == "finish"
            and conversation is not None
            and conversation.has_unverified_changes(self.policy)
            and not self.policy.classify_finish_message(
                getattr(action, "message", "")
            ).verification_unavailable
        ):
            return ToolResult(
                "Verification required before finishing: run a focused test, "
                "lint/typecheck/build command, or explain in the finish message why "
                "verification cannot be run.",
                True,
            )

        # The plan lives on the conversation, which tools never see, so the
        # step mutation happens here; the tool's observation reports it.
        if call.name == "update_plan":
            if conversation is None:
                return ToolResult("update_plan requires a live conversation.", True)
            plan = conversation.plan
            if plan is None or not (1 <= action.step <= len(plan.steps)):
                return ToolResult(
                    f"Invalid step: the approved plan has no step {action.step}.",
                    True,
                )
            plan.steps[action.step - 1].status = action.status

        try:
            if call.name in ("fanout", "web_research") and conversation is not None:
                observation = tool.execute(
                    action,
                    sandbox,
                    conversation=conversation,
                    tool_call_id=call.id,
                )
            else:
                observation = tool.execute(action, sandbox)
        except SandboxError:
            # The model cannot fix an unreachable or expired sandbox; end the
            # turn instead of feeding it an error to retry.
            raise
        except Exception as exc:
            return ToolResult(f"Tool error: {exc}", True)

        try:
            content = observation.to_llm_text()
        except Exception as exc:
            return ToolResult(f"Tool returned an invalid observation: {exc}", True)

        return ToolResult(
            content,
            getattr(observation, "error", False),
            getattr(observation, "duration_ms", None),
            observation.ui_details(),
        )

    def _is_mcp(self, action_event: ActionEvent) -> bool:
        return action_event.tool_name.startswith(MCP_PREFIX)

    def _is_read_only_mcp(self, action_event: ActionEvent) -> bool:
        name = action_event.tool_name
        if not self._is_mcp(action_event) or name not in self.tools:
            return False
        return isinstance(tool := self.tools[name], McpTool) and tool.read_only

    def _blocked_in_plan_mode(self, action_event: ActionEvent) -> bool:
        if self._is_mcp(action_event):
            return not self._is_read_only_mcp(action_event)
        if action_event.tool_name == "file_edit":
            return action_event.arguments.get("command") in ("create", "str_replace")
        if action_event.tool_name == "bash":
            return not self.policy.classify_bash(
                action_event.arguments.get("command", "")
            ).read_only
        return False

    def _needs_confirmation(
        self, action_event: ActionEvent, conversation: Conversation
    ) -> bool:
        mode = conversation.confirm_policy.mode
        if mode == "never":
            return False
        if mode == "always":
            return True
        if action_event.tool_name == "bash":
            return self.policy.classify_bash(
                action_event.arguments.get("command", "")
            ).needs_confirmation
        if self._is_read_only_mcp(action_event):
            return False
        return conversation.needs_confirmation(action_event)

    @staticmethod
    def _prior_identical_calls(conversation: Conversation, call: ToolCall) -> int:
        """How many already-observed calls match this tool name + arguments."""
        observed = {
            e.tool_call_id
            for e in conversation.events
            if isinstance(e, ObservationEvent)
        }
        sig = (call.name, json.dumps(call.arguments, sort_keys=True))
        return sum(
            1
            for e in conversation.events
            if isinstance(e, ActionEvent)
            and e.tool_call_id in observed
            and (e.tool_name, json.dumps(e.arguments, sort_keys=True)) == sig
        )

    @staticmethod
    def _observe(
        conversation: Conversation,
        call: ToolCall,
        content: str,
        error: bool,
        duration_ms: int | None = None,
        details: dict | None = None,
    ) -> None:
        # A weak model can get stuck re-issuing an identical call (a failing
        # str_replace, an invalid-args retry) and burn every iteration on it.
        # Append a pointed nudge so the model sees it's looping and
        # course-corrects before the stuck detector pauses the run.
        repeats = Agent._prior_identical_calls(conversation, call)
        if repeats >= _NUDGE_AFTER_REPEATS:
            content += (
                f"\n\n[note] You have already run this exact call {repeats} times "
                "with the same result. Stop repeating it; re-read the file or "
                "inputs and fix the problem, take a different action, or call "
                "`finish` if you're done or stuck."
            )
        conversation.add_event(
            ObservationEvent(
                tool_name=call.name,
                tool_call_id=call.id,
                content=content,
                error=error,
                duration_ms=duration_ms,
                details=details,
            )
        )
