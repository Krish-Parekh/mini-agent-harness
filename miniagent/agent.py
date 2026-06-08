from __future__ import annotations

from typing import TYPE_CHECKING, Literal, TypeAlias

from pydantic import ValidationError

from miniagent.events import ActionEvent, ErrorEvent, MessageEvent, ObservationEvent
from miniagent.llm import LLM, ToolCall
from miniagent.text import clip
from miniagent.tools.base import ToolRegistry

if TYPE_CHECKING:
    from miniagent.conversation import Conversation
    from miniagent.sandbox.base import Sandbox

ToolOutcome: TypeAlias = Literal["ok", "finished", "paused"]

# Per-message ceiling sent to the LLM; long tool output is head+tail clipped.
_MAX_MESSAGE_CHARS = 12_000


DEFAULT_SYSTEM_PROMPT = """You are MiniAgent, a coding agent that works on a software project inside an \
isolated sandbox workspace. The code lives at the working directory and all your tools run there.

You act only through tools — you never touch the world directly. Each turn you either call a tool \
or, when the task is fully complete and verified, call the `finish` tool. Do not end a turn with a \
plain message assuming the work is done; the loop only stops when you call `finish`.

# Tools
- `bash`: run a shell command in the workspace — build, run code, run tests, search, inspect git. \
Use it for anything other than reading or writing a single file.
- `file_edit`:
  - `view` — read a file before changing it.
  - `create` — write a new file (provide the full `content`).
  - `str_replace` — make a targeted edit; `old_str` must match exactly and appear exactly once, so \
include enough surrounding context to be unique.
- `finish`: end the task with a short summary of what you did.

# How to work
- Treat instructions as software-engineering tasks against the actual code. If asked to rename \
`methodName`, find it in the code and change it — don't just answer in chat.
- Explore before editing: read the relevant files and follow the existing conventions, then make \
the smallest change that satisfies the task. Match the surrounding code's style.
- Don't add features, refactors, abstractions, error handling, or compatibility shims beyond what \
the task requires. Three similar lines beat a premature abstraction. Only validate at real \
boundaries (user input, external APIs); trust internal code. No half-finished work.
- Verify your change by running the code or its tests with `bash`. Don't assume it works — confirm it.
- Keep tool use efficient: read the parts of a file you need rather than dumping whole files, and \
prefer small `str_replace` edits over rewriting entire files.

# Acting with care
- Local, reversible actions (editing files, running tests) are fine to take freely. Be careful with \
destructive or hard-to-reverse commands (rm -rf, git reset --hard, force-push, dropping data).
- Don't use destructive shortcuts to get past an obstacle. Find and fix the root cause instead of \
bypassing safety checks (e.g. --no-verify). If you find unexpected files or state, investigate \
before deleting or overwriting — it may be the user's in-progress work.

# Finishing
- When the task is done and verified, call `finish` with a brief, truthful summary of what changed.
- Report outcomes honestly: if tests fail or a step was skipped, say so. State what is done plainly, \
without hedging or overclaiming. Reference code as `path:line` when useful.
"""


class Agent:
    def __init__(
        self,
        llm: LLM,
        tools: ToolRegistry,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    ) -> None:
        self.llm = llm
        self.tools = tools
        self.system_prompt = system_prompt

    def step(self, conversation: Conversation, sandbox: Sandbox) -> None:
        pending = conversation.pending_action()
        if pending is not None:
            call = ToolCall(
                id=pending.tool_call_id,
                name=pending.tool_name,
                arguments=pending.arguments,
            )
            self._run_tool(call, conversation, sandbox)
            return

        messages = self._build_messages(conversation)
        response = self.llm.complete(messages, self.tools.all())

        if response.text:
            conversation.add_event(MessageEvent(role="assistant", text=response.text))

        if response.tool_calls:
            for call in response.tool_calls:
                outcome = self._handle_tool_call(call, conversation, sandbox)
                if outcome in ("finished", "paused"):
                    break
        elif not response.text:
            conversation.add_event(ErrorEvent(message="empty model response"))

    def _build_messages(self, conversation: Conversation) -> list[dict]:
        messages: list[dict] = [{"role": "system", "content": self.system_prompt}]
        for event in conversation.events:
            message = event.to_chat_message()
            if message is None:
                continue
            # Clip oversized content so one giant observation can't exhaust the
            # context window; truncating (not dropping events) keeps tool_call
            # pairing intact, and clipping at send-time also rescues stored events.
            content = message.get("content")
            if isinstance(content, str):
                message = {**message, "content": clip(content, _MAX_MESSAGE_CHARS)}
            messages.append(message)
        return messages

    def _handle_tool_call(
        self, call: ToolCall, conversation: Conversation, sandbox: Sandbox
    ) -> ToolOutcome:
        action_event = ActionEvent(
            tool_name=call.name,
            arguments=call.arguments,
            tool_call_id=call.id,
        )
        conversation.add_event(action_event)

        if conversation.needs_confirmation(action_event):
            conversation.set_waiting_for_confirmation()
            return "paused"

        finished = self._run_tool(call, conversation, sandbox)
        return "finished" if finished else "ok"

    def _run_tool(
        self, call: ToolCall, conversation: Conversation, sandbox: Sandbox
    ) -> bool:
        if call.name not in self.tools:
            available = ", ".join(t.name for t in self.tools.all())
            self._observe(
                conversation,
                call,
                f"Unknown tool: {call.name}. Available: {available}",
                True,
            )
            return False

        tool = self.tools[call.name]
        try:
            action = tool.action_type(**call.arguments)
        except ValidationError as exc:
            self._observe(conversation, call, f"Invalid arguments: {exc}", True)
            return False

        try:
            observation = tool.execute(action, sandbox)
        except Exception as exc:
            self._observe(conversation, call, f"Tool error: {exc}", True)
            return False

        self._observe(
            conversation,
            call,
            observation.to_llm_text(),
            getattr(observation, "error", False),
        )

        if call.name == "finish":
            conversation.set_finished()
            return True
        return False

    @staticmethod
    def _observe(
        conversation: Conversation, call: ToolCall, content: str, error: bool
    ) -> None:
        conversation.add_event(
            ObservationEvent(
                tool_name=call.name,
                tool_call_id=call.id,
                content=content,
                error=error,
            )
        )
