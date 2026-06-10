from __future__ import annotations

import json
from typing import TYPE_CHECKING, Literal, TypeAlias

from pydantic import ValidationError

from miniagent.confirm import blocked_in_plan_mode
from miniagent.events import ActionEvent, ErrorEvent, MessageEvent, ObservationEvent
from miniagent.llm import LLM, ToolCall
from miniagent.text import clip
from miniagent.tools.base import ToolRegistry
from miniagent.tools.plan import Plan

if TYPE_CHECKING:
    from miniagent.conversation import Conversation
    from miniagent.sandbox.base import Sandbox

ToolOutcome: TypeAlias = Literal["ok", "finished", "paused"]

# Per-message ceiling sent to the LLM; long tool output is head+tail clipped.
_MAX_MESSAGE_CHARS = 12_000

# A weak model can get wedged re-issuing one identical call. We first nudge it in
# the observation; if it ignores that and keeps going, abort the run rather than
# letting it burn every iteration on the same no-op.
_NUDGE_AFTER_REPEATS = 2
_ABORT_AFTER_REPEATS = 5


DEFAULT_SYSTEM_PROMPT = """You are MiniAgent, a coding agent that works on a software project inside an \
isolated sandbox workspace. The code lives at the working directory and all your tools run there.

You act only through tools — you never touch the world directly. Each turn you either call a tool \
or, when the task is fully complete and verified, call the `finish` tool. Do not end a turn with a \
plain message assuming the work is done; the loop only stops when you call `finish`.

# Tools
- `bash`: run a shell command in the workspace — build, run code, run tests, search, inspect git. \
Use it for anything other than reading or writing a single file.
- `file_edit`:
  - `view` — read a file before changing it. Returns the raw file text exactly as stored, with \
no line-number prefixes; pass `view_range=[start, end]` (1-based, end -1 = EOF) for a slice. To \
find line numbers, use `bash` (`rg -n`, `sed -n`).
  - `create` — write a new file (provide the full `content`).
  - `str_replace` — make a targeted edit; `old_str` must match the raw file bytes exactly — copy \
it from `view` output, never paste line-number prefixes — and appear exactly once, so include \
enough surrounding context to be unique.
- `finish`: end the task with a short summary of what you did.

# Bash workflow
- Explore with search, not guesswork: `rg -n "pattern" path/` (fall back to `grep -rn`) to find \
code, `git ls-files | rg name` or `find` to locate files, `sed -n '40,90p' file` to read a slice. \
Use `git log --oneline -10`, `git diff`, and `git status` to understand the repo's state. \
Use `file_edit view` for a file you're about to edit; bash for anything search- or multi-file-shaped.
- Verify in a tight loop: reproduce the problem before fixing it, and after each meaningful change \
run the narrowest check that exercises it — a single test file (`python -m pytest tests/test_x.py \
-x -q`), a build, an import — rather than batching many edits before the first verification.
- Keep output small (`| head -50`, `--oneline`, `-q`) and never run interactive or watch-mode \
commands (editors, REPLs, `npm run dev`). The default timeout is 30s; pass a larger `timeout` \
(120-600) for installs, builds, and full test suites, and prefer narrow invocations over \
suite-wide runs.

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


# Appended to the system prompt for a turn when the user has planning mode on.
PLAN_MODE_DIRECTIVE = """

# Planning mode is ON
The user wants a plan before any changes are made. For now:
- Explore the relevant code read-only — read files, search, inspect git — to ground the \
plan in how things actually work. Actions that modify the workspace are blocked while \
planning; don't attempt them.
- If the task is ambiguous or could reasonably go more than one way, call `ask_user` with \
a few multiple-choice questions to settle the key decisions before you write the plan.
- Then call `present_plan` with a short title and the ordered steps: each step has an \
imperative title, the files it touches, and a one-to-two sentence description. Keep it \
tight — no code dumps.
- Calling `present_plan` ends your turn. Do not call `finish` and do not start \
implementing. If the user replies with feedback instead of approving, refine the plan \
and present it again.
"""


IMPLEMENT_PLAN_DIRECTIVE = """

# Approved plan
{plan}

Follow the steps in order. Call `update_plan` to mark a step `in_progress` before \
starting it and `done` once implemented and verified. If the plan turns out to be \
wrong, say so and adapt rather than following it blindly. Call `finish` when every \
step is done.
"""


class Agent:
    def __init__(
        self,
        llm: LLM,
        tools: ToolRegistry,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        repo: str | None = None,
        branch: str | None = None,
    ) -> None:
        self.llm = llm
        self.tools = tools
        self.system_prompt = system_prompt
        self.repo = repo
        self.branch = branch

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

        messages = self._build_messages(conversation, sandbox)
        response = self.llm.complete(messages, self.tools.all())

        if response.text:
            conversation.add_event(MessageEvent(role="assistant", text=response.text))

        if response.tool_calls:
            for call in response.tool_calls:
                outcome = self._handle_tool_call(call, conversation, sandbox)
                if outcome in ("finished", "paused"):
                    break
            return

        # No tool call ends the turn; re-prompting here would loop to the cap.
        if not response.text:
            conversation.add_event(ErrorEvent(message="empty model response"))
        conversation.set_idle()

    def _context_block(self, conversation: Conversation, sandbox: Sandbox) -> str:
        """Workspace context appended to the system prompt every turn.

        Read at message-build time, not construction time: bootstrap moves the
        sandbox into the worktree after the agent is built.
        """
        lines = ["\n\n# Workspace"]
        if self.repo:
            branch = f" (branch: {self.branch})" if self.branch else ""
            lines.append(f"- repository: {self.repo}{branch}")
        lines.append(f"- working directory: {sandbox.workspace_dir}")
        lines.append("Relative paths resolve against the working directory.")
        block = "\n".join(lines)
        if conversation.implementing_plan:
            result = sandbox.run_command("git status --porcelain", timeout=10)
            status = result.stdout.strip()
            if result.exit_code == 0 and status:
                block += "\n\n## Uncommitted changes (git status --porcelain)\n"
                block += clip(status, 1_500)
        return block

    def _build_messages(
        self, conversation: Conversation, sandbox: Sandbox
    ) -> list[dict]:
        system_prompt = self.system_prompt + self._context_block(conversation, sandbox)
        if conversation.plan_mode:
            system_prompt += PLAN_MODE_DIRECTIVE
        elif conversation.implementing_plan and conversation.plan is not None:
            system_prompt += IMPLEMENT_PLAN_DIRECTIVE.format(
                plan=conversation.plan.render()
            )
        messages: list[dict] = [{"role": "system", "content": system_prompt}]
        pending: dict | None = None  # assistant turn being assembled

        def flush() -> None:
            nonlocal pending
            if pending is not None:
                messages.append(pending)
                pending = None

        for event in conversation.events:
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
                            "arguments": json.dumps(event.arguments),
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
            # Clip oversized content so one giant observation can't exhaust the
            # context window; truncating (not dropping events) keeps tool_call
            # pairing intact, and clipping at send-time also rescues stored events.
            content = message.get("content")
            if isinstance(content, str):
                message = {**message, "content": clip(content, _MAX_MESSAGE_CHARS)}
            messages.append(message)

        flush()
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

        # Hard stop: the model has ignored the nudge and is stuck on one call.
        # Abort the run with a clear error instead of grinding to max iterations.
        if self._prior_identical_calls(conversation, call) >= _ABORT_AFTER_REPEATS:
            conversation.add_event(
                ErrorEvent(
                    message=(
                        f"stopped: repeated the same {call.name} call "
                        f"{_ABORT_AFTER_REPEATS}+ times without making progress"
                    )
                )
            )
            conversation.set_error()
            return "paused"

        if conversation.plan_mode and blocked_in_plan_mode(action_event):
            self._observe(
                conversation,
                call,
                "Plan mode is active — this action would modify the workspace. "
                "Explore read-only and call `present_plan` when ready.",
                True,
            )
            return "ok"

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

        # The plan lives on the conversation, which tools never see, so the
        # step mutation happens here; the tool's observation reports it.
        if call.name == "update_plan":
            plan = conversation.plan
            if plan is None or not (1 <= action.step <= len(plan.steps)):
                self._observe(
                    conversation,
                    call,
                    f"Invalid step: the approved plan has no step {action.step}.",
                    True,
                )
                return False
            plan.steps[action.step - 1].status = action.status

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
            getattr(observation, "duration_ms", None),
        )

        if call.name == "finish":
            conversation.implementing_plan = False
            conversation.set_finished()
            return True
        if call.name == "present_plan":
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
    ) -> None:
        # A weak model can get stuck re-issuing an identical call — a failing
        # str_replace, an invalid-args retry — and burn every iteration on it.
        # Once it's repeated, append a pointed nudge to the result (whatever the
        # outcome) so the model sees it's looping and course-corrects or finishes.
        repeats = Agent._prior_identical_calls(conversation, call)
        if repeats >= _NUDGE_AFTER_REPEATS:
            content += (
                f"\n\n[note] You have already run this exact call {repeats} times "
                "with the same result. Stop repeating it — re-read the file or "
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
            )
        )
