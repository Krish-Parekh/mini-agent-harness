from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import logfire
from pydantic import BaseModel

from miniagent.config import Settings
from miniagent.factory import build_agent
from miniagent.confirm import ConfirmMode, ConfirmPolicy
from miniagent.conversation import Conversation, Status
from miniagent.events import Attachment, ErrorEvent, Event, MessageEvent
from miniagent.sandbox.base import Sandbox, SandboxError
from miniagent.sandbox import docker as docker_sandbox
from miniagent.sandbox.factory import build_sandbox, default_provider, is_host_git
from miniagent.sandbox.workspace import WorkspaceError, clone_repo
from backend.repository.memory import MemoryRepository
from backend.runtime import mcp
from backend.runtime.memory import DbMemoryStore
from backend.runtime.workspaces import BRANCH_PREFIX, WorkspaceManager
from miniagent.tools.mcp import MAX_TOOLS as MAX_MCP_TOOLS, McpTool
from miniagent.tools.skill import SkillTool
from miniagent.tools.plan import Plan

PersistHook = Callable[["ManagedConversation", Event, int], None]


def publish_committed(managed: ManagedConversation, event: Event, seq: int) -> None:
    managed.persisted_seq = seq
    managed.broker.publish_event(event, seq)

_log = logging.getLogger(__name__)

MCP_INSTRUCTIONS_MAX_CHARS = 1_000


def _mcp_invoker(session: mcp.McpSession):
    def invoke(tool_name: str, arguments: dict) -> str:
        return mcp.bridge.run(session.call(tool_name, arguments))

    return invoke


AI_TITLE_AFTER_TURNS = 4
TITLE_SNIPPET_CHARS = 60

_TITLE_SYSTEM = (
    "You write a short, specific title for a coding conversation. "
    "Reply with the title only: 3 to 6 words, no quotes, no trailing "
    "punctuation."
)

_PR_SYSTEM = (
    "You write the commit message and pull request for a coding agent's changes. "
    "Use the conversation for intent and the diff for what changed. "
    "commit_message: an imperative subject line under 72 characters, optionally "
    "followed by a blank line and a short body. title: under 70 characters. "
    "body: markdown summarising what changed and why; if a pull request template "
    "is given, fill in its sections. Do not invent changes that are not in the diff."
)


class PrDraft(BaseModel):
    commit_message: str
    title: str
    body: str


def title_snippet(text: str, limit: int = TITLE_SNIPPET_CHARS) -> str:
    stripped = text.strip()
    line = stripped.splitlines()[0].strip() if stripped else ""
    if len(line) <= limit:
        return line
    cut = line[:limit].rsplit(" ", 1)[0]
    return cut.rstrip(" ,.;:-") + "…"


@dataclass(frozen=True)
class StreamFrame:
    event: Event
    seq: int | None


@dataclass(frozen=True)
class QueuedMessage:
    id: str
    text: str
    attachments: list[Attachment]
    model: str | None
    client_event_id: str | None


class EventBroker:
    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self._subscribers: set[asyncio.Queue[Any]] = set()

    def subscribe(self) -> asyncio.Queue[Any]:
        queue: asyncio.Queue[Any] = asyncio.Queue()
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[Any]) -> None:
        self._subscribers.discard(queue)

    def publish(self, item: Any) -> None:
        for queue in list(self._subscribers):
            self._loop.call_soon_threadsafe(queue.put_nowait, item)

    def publish_event(self, event: Event, seq: int | None) -> None:
        self.publish(StreamFrame(event=event, seq=seq))


class ManagedConversation:

    def __init__(
        self,
        conversation: Conversation,
        sandbox: Sandbox,
        broker: EventBroker,
        workspaces: WorkspaceManager,
        user_id: uuid.UUID,
        repo: str | None = None,
        branch: str | None = None,
        token: str | None = None,
    ) -> None:
        self.conversation = conversation
        self.sandbox = sandbox
        self.broker = broker
        self._workspaces = workspaces
        self.user_id = user_id
        self.repo = repo
        self.branch = branch
        self._token = token
        self.title: str | None = None
        self._ai_titled = False
        self.pr_number: int | None = None
        self.pr_url: str | None = None
        self._seq = 0
        self.persisted_seq = 0
        self.run_generation = 0
        self.lock = asyncio.Lock()
        self.persist_hook: PersistHook = publish_committed
        self.mcp_tools: dict[str, list[str]] = {}
        self.mcp_sessions: dict[str, mcp.McpSession] = {}
        self.mcp_skipped: set[str] = set()
        self.mcp_instructions: dict[str, tuple[str, str]] = {}
        self.skills_skipped: set[str] = set()
        self.queue: list[QueuedMessage] = []

    def on_event(self, event: Event) -> None:
        self._seq += 1
        self._maybe_set_title(event)
        self.persist_hook(self, event, self._seq)

    def set_model(self, model: str) -> None:
        self.conversation.agent.llm.model = model

    def _maybe_set_title(self, event: Event) -> None:
        if self.title is not None:
            return
        if not (isinstance(event, MessageEvent) and event.role == "user"):
            return
        snippet = title_snippet(event.text)
        base = self.repo.split("/")[-1] if self.repo else None
        title = f"{base}: {snippet}".strip(": ") if base else snippet
        self.title = title or None

    def user_turns(self) -> int:
        return sum(
            1
            for e in self.conversation.events
            if isinstance(e, MessageEvent) and e.role == "user"
        )

    def build_title(self) -> str | None:
        transcript = self._title_transcript()
        if not transcript:
            return None
        agent = self.conversation.agent
        llm = getattr(agent.policy, "llm", agent.llm)
        response = llm.complete(
            [
                {"role": "system", "content": _TITLE_SYSTEM},
                {"role": "user", "content": transcript},
            ],
            phase="title",
        )
        text = (response.text or "").strip().strip('"').strip()
        snippet = text.splitlines()[0][:60] if text else ""
        if not snippet:
            return None
        base = self.repo.split("/")[-1] if self.repo else None
        return f"{base}: {snippet}" if base else snippet

    def draft_pr(self, diff: str, template: str | None) -> PrDraft:
        agent = self.conversation.agent
        llm = getattr(agent.policy, "llm", agent.llm)
        sections = [
            f"Conversation:\n{self._title_transcript()}",
            f"Diff:\n{diff or '(no new changes)'}",
        ]
        if template:
            sections.append(f"Pull request template:\n{template}")
        return llm.complete_structured(
            [
                {"role": "system", "content": _PR_SYSTEM},
                {"role": "user", "content": "\n\n".join(sections)},
            ],
            PrDraft,
            phase="pr_draft",
        )

    def _title_transcript(self) -> str:
        lines: list[str] = []
        for e in self.conversation.events:
            if isinstance(e, MessageEvent) and e.role in ("user", "assistant"):
                text = e.text.strip()
                if text:
                    lines.append(f"{e.role}: {text[:500]}")
        return "\n".join(lines[:12])

    def apply_extensions(
        self,
        skill_catalog: str,
        skill_bodies: dict[str, str],
        targets: dict[str, mcp.McpTarget],
    ) -> None:
        agent = self.conversation.agent
        agent.skills_block = skill_catalog
        registry = agent.tools
        if skill_bodies:
            registry.register(SkillTool(skill_bodies))
        else:
            registry.unregister(SkillTool.name)
        for connection_id in list(self.mcp_tools):
            if connection_id not in targets:
                self._drop_mcp(connection_id)
        self.mcp_skipped &= targets.keys()

        registered = sum(len(names) for names in self.mcp_tools.values())
        for connection_id, target in targets.items():
            if connection_id in self.mcp_tools or connection_id in self.mcp_skipped:
                continue
            session = mcp.McpSession(target)
            try:
                with logfire.span("mcp.open", connection=target.name) as span:
                    info = mcp.bridge.run(session.open())
                    specs = info.tools
                    span.set_attribute("tool_count", len(specs))
            except mcp.McpError as exc:
                self.mcp_skipped.add(connection_id)
                self.conversation.add_event(
                    ErrorEvent(
                        message=f"MCP server '{target.name}' is unavailable: {exc}"
                    )
                )
                continue
            if registered + len(specs) > MAX_MCP_TOOLS:
                mcp.bridge.run(session.close())
                self.mcp_skipped.add(connection_id)
                self.conversation.add_event(
                    ErrorEvent(
                        message=(
                            f"MCP connection '{target.name}' was skipped: its "
                            f"{len(specs)} tools would exceed the {MAX_MCP_TOOLS}-tool "
                            "budget."
                        )
                    )
                )
                continue
            names: list[str] = []
            for spec in specs:
                tool = McpTool(
                    connection=target.name,
                    remote_name=spec.name,
                    description=spec.description,
                    input_schema=spec.input_schema,
                    invoke=_mcp_invoker(session),
                    read_only=spec.read_only,
                )
                if tool.name in registry:
                    _log.warning(
                        "skipping MCP tool %s: name already registered", tool.name
                    )
                    continue
                registry.register(tool)
                names.append(tool.name)
            self.mcp_tools[connection_id] = names
            self.mcp_sessions[connection_id] = session
            registered += len(names)
            if info.instructions:
                self.mcp_instructions[connection_id] = (
                    target.name,
                    info.instructions[:MCP_INSTRUCTIONS_MAX_CHARS],
                )
        agent.mcp_instructions = dict(self.mcp_instructions.values())

    def _drop_mcp(self, connection_id: str) -> None:
        for name in self.mcp_tools.pop(connection_id):
            self.conversation.agent.tools.unregister(name)
        self.mcp_instructions.pop(connection_id, None)
        mcp.bridge.run(self.mcp_sessions.pop(connection_id).close())

    def close_mcp(self) -> None:
        for connection_id in list(self.mcp_tools):
            self._drop_mcp(connection_id)
        self.mcp_skipped.clear()
        self.conversation.agent.mcp_instructions = {}

    @property
    def host_workspace(self) -> Path | None:
        if not is_host_git(self.sandbox.provider):
            return None
        return Path(self.sandbox.workspace_dir)

    def bootstrap(self) -> None:
        if not self.repo:
            return
        try:
            if is_host_git(self.sandbox.provider):
                checkout = self._workspaces.prepare(
                    self.conversation.id, self.repo, self.branch, self._token
                )
                self.sandbox.set_working_dir(checkout)
            else:
                clone_repo(
                    self.sandbox,
                    self.repo,
                    self.branch,
                    self._token,
                    f"{BRANCH_PREFIX}/{self.conversation.id}",
                )
        except SandboxError as exc:
            self.conversation.add_event(
                ErrorEvent(message=f"sandbox_unavailable: {self.sandbox.provider}: {exc}")
            )
            self.conversation.status = Status.ERROR
        except WorkspaceError as exc:
            self.conversation.add_event(
                ErrorEvent(message=f"workspace setup failed: {exc}")
            )
            self.conversation.status = Status.ERROR

    def extend_sandbox(self, seconds: int) -> None:
        try:
            self.sandbox.extend(seconds)
        except SandboxError:
            pass


class ConversationManager:

    def __init__(
        self,
        settings: Settings,
        data_dir: Path = Path("data"),
        memories: MemoryRepository | None = None,
    ) -> None:
        self._settings = settings
        self._memories = memories
        self._workspaces = WorkspaceManager(data_dir)
        self._conversations: dict[str, ManagedConversation] = {}
        self._persist_hook: PersistHook = publish_committed

    def set_persist_hook(self, hook: PersistHook) -> None:
        self._persist_hook = hook

    def create(
        self,
        *,
        user_id: uuid.UUID,
        repo: str | None = None,
        branch: str | None = None,
        workspace_dir: str | None = None,
        confirm_mode: ConfirmMode = "risky",
        token: str | None = None,
        provider: str | None = None,
    ) -> ManagedConversation:
        cid = uuid.uuid4().hex[:8]
        provider = provider or default_provider(self._settings)
        if not is_host_git(provider):
            ws = None
        elif repo:
            ws = str(self._workspaces.checkout_dir(cid))
        elif provider == "docker":
            ws = self._workspaces.empty_checkout(cid)
        else:
            ws = workspace_dir or self._settings.workspace_dir
        sandbox = self._sandbox(cid, provider, ws, None, repo)
        return self._build(cid, sandbox, confirm_mode, user_id, repo, branch, token)

    def _sandbox(
        self,
        cid: str,
        provider: str,
        workspace_dir: str | None,
        sandbox_id: str | None,
        repo: str | None,
    ) -> Sandbox:
        return build_sandbox(
            self._settings,
            cid,
            provider=provider,
            workspace_dir=workspace_dir,
            sandbox_id=sandbox_id,
            host_mounts=self._workspaces.mounts(cid, repo),
        )

    @property
    def sandbox_lifetime_s(self) -> int:
        return self._settings.sandbox_lifetime_s

    @property
    def sandbox_idle_stop_s(self) -> int:
        return self._settings.sandbox_idle_stop_s

    def live(self) -> list[ManagedConversation]:
        return list(self._conversations.values())

    def sandbox_containers(self) -> dict[str, str]:
        return docker_sandbox.conversation_containers()

    def remove_containers(self, containers: dict[str, str]) -> None:
        docker_sandbox.remove_containers(containers)

    def destroy_sandbox(
        self, cid: str, provider: str, sandbox_id: str | None, workspace_dir: str | None
    ) -> None:
        """Delete a sandbox that has no live Conversation, e.g. one bound to a
        row that was never revived. Blocking."""
        if is_host_git(provider) and provider != "docker":
            return
        if not sandbox_id:
            return
        self._sandbox(cid, provider, workspace_dir, sandbox_id, None).close()

    def release_workspace(self, cid: str, repo: str | None) -> None:
        self._workspaces.release(cid, repo)

    def register_revived(
        self,
        *,
        cid: str,
        user_id: uuid.UUID,
        repo: str | None,
        branch: str | None,
        workspace_dir: str | None,
        status: str,
        title: str | None,
        events: list[Event],
        plan: dict | None = None,
        implementing_plan: bool = False,
        pr_number: int | None = None,
        pr_url: str | None = None,
        token: str | None = None,
        sandbox_provider: str = "local",
        sandbox_id: str | None = None,
    ) -> ManagedConversation:
        if is_host_git(sandbox_provider):
            ws = workspace_dir or self._settings.workspace_dir
        else:
            ws = workspace_dir or None
        sandbox = self._sandbox(cid, sandbox_provider, ws, sandbox_id, repo)
        managed = self._build(cid, sandbox, "risky", user_id, repo, branch, token)
        managed.conversation.events = events
        managed.conversation.plan = Plan.model_validate(plan) if plan else None
        managed.conversation.implementing_plan = implementing_plan
        managed.title = title
        managed._ai_titled = managed.user_turns() >= AI_TITLE_AFTER_TURNS
        managed.pr_number = pr_number
        managed.pr_url = pr_url
        managed._seq = len(events)
        managed.persisted_seq = len(events)
        try:
            managed.conversation.status = Status(status)
        except ValueError:
            managed.conversation.status = Status.IDLE
        return managed

    def _build(
        self,
        cid: str,
        sandbox: Sandbox,
        confirm_mode: ConfirmMode,
        user_id: uuid.UUID,
        repo: str | None,
        branch: str | None,
        token: str | None,
    ) -> ManagedConversation:
        loop = asyncio.get_running_loop()
        memory = (
            DbMemoryStore(self._memories, loop, user_id, repo, cid)
            if self._memories is not None
            else None
        )
        conversation = Conversation(
            agent=build_agent(
                self._settings,
                preset="interactive",
                repo=repo,
                branch=branch,
                memory=memory,
            ),
            sandbox=sandbox,
            max_iterations=self._settings.max_iterations,
            confirm_policy=ConfirmPolicy(confirm_mode),
            id=cid,
        )
        managed = ManagedConversation(
            conversation,
            sandbox,
            EventBroker(loop),
            self._workspaces,
            user_id,
            repo,
            branch,
            token,
        )
        managed.persist_hook = self._persist_hook
        conversation.on_event = managed.on_event
        self._conversations[cid] = managed
        return managed

    def get(self, cid: str) -> ManagedConversation | None:
        return self._conversations.get(cid)

    def remove(self, cid: str) -> ManagedConversation | None:
        return self._conversations.pop(cid, None)
