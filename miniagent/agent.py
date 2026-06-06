from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import ValidationError

from miniagent.events import ActionEvent, ErrorEvent, MessageEvent, ObservationEvent
from miniagent.llm import LLM, ToolCall
from miniagent.tools.base import ToolRegistry

if TYPE_CHECKING:
    from miniagent.conversation import Conversation
    from miniagent.sandbox.base import Sandbox


DEFAULT_SYSTEM_PROMPT = """You are a coding agent working inside a sandboxed workspace.

You act only through tools. Each turn, either call a tool or, when the task is
complete, call the `finish` tool with a short summary. Do not stop by just
writing a message.

How to work:
- Explore before editing: read files to understand the code first.
- Make minimal, targeted changes. Prefer small str_replace edits over rewriting files.
- Verify your work by running commands (e.g. run the file or its tests).
- Keep tool output small: read the parts you need, not whole large files.

When the task is done and verified, call `finish`.
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
        messages = self._build_messages(conversation)
        response = self.llm.complete(messages, self.tools.all())

        if response.text:
            conversation.add_event(MessageEvent(role="assistant", text=response.text))

        if response.tool_calls:
            for call in response.tool_calls:
                finished = self._handle_tool_call(call, conversation, sandbox)
                if finished:
                    break
        elif not response.text:
            conversation.add_event(ErrorEvent(message="empty model response"))

    def _build_messages(self, conversation: Conversation) -> list[dict]:
        messages: list[dict] = [{"role": "system", "content": self.system_prompt}]
        for event in conversation.events:
            message = event.to_chat_message()
            if message is not None:
                messages.append(message)
        return messages

    def _handle_tool_call(
        self, call: ToolCall, conversation: Conversation, sandbox: Sandbox
    ) -> bool:
        # Always log the intent, so every tool_call is paired with a result.
        conversation.add_event(
            ActionEvent(
                tool_name=call.name,
                arguments=call.arguments,
                tool_call_id=call.id,
            )
        )

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
