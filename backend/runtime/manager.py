from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Callable

from miniagent.agent import Agent
from miniagent.classification import TaskClassifier
from miniagent.config import Settings
from miniagent.confirm import ConfirmMode, ConfirmPolicy
from miniagent.conversation import Conversation, Status
from miniagent.events import ErrorEvent, Event, MessageEvent
from miniagent.llm import LLM
from miniagent.policy import PolicyClassifier
from miniagent.sandbox.local import LocalSandbox
from miniagent.sandbox.workspace import WorkspaceError
from backend.runtime.workspaces import WorkspaceManager
from miniagent.tools.bash import BashTool
from miniagent.tools.base import ToolRegistry
from miniagent.tools.file_edit import FileEditTool
from miniagent.tools.finish import FinishTool
from miniagent.tools.ask import AskUserTool
from miniagent.tools.fanout import FanoutTool
from miniagent.tools.plan import Plan, PresentPlanTool, UpdatePlanTool
from miniagent.tools.fetch_url import FetchUrlTool
from miniagent.tools.web_research import WebResearchTool
from miniagent.tools.web_search import WebSearchTool

PersistHook = Callable[["ManagedConversation", Event, int], None]

AI_TITLE_AFTER_TURNS = 4

_TITLE_SYSTEM = (
    "You write a short, specific title for a coding conversation. "
    "Reply with the title only: 3 to 6 words, no quotes, no trailing "
    "punctuation."
)


def _build_agent(
    settings: Settings,
    repo: str | None,
    branch: str | None,
) -> Agent:
    llm = LLM(
        model=settings.model,
        temperature=settings.temperature,
        max_tokens=settings.max_tokens,
    )
    policy = PolicyClassifier(
        LLM(
            model=settings.policy_model,
            temperature=0.0,
            max_tokens=1024,
        )
    )
    task_router = TaskClassifier(
        LLM(
            model=settings.policy_model,
            temperature=0.0,
            max_tokens=512,
        )
    )
    tool_list: list = [
        BashTool(),
        FileEditTool(),
        FinishTool(),
        PresentPlanTool(),
        UpdatePlanTool(),
        AskUserTool(),
        FanoutTool(llm, repo, branch, policy),
    ]
    if settings.tavily_api_key:
        web_search = WebSearchTool(settings.tavily_api_key)
        fetch_url = FetchUrlTool()
        tool_list.extend(
            [
                web_search,
                fetch_url,
                WebResearchTool(llm, web_search, fetch_url),
            ]
        )
    tools = ToolRegistry(tool_list)
    return Agent(
        llm=llm,
        tools=tools,
        repo=repo,
        branch=branch,
        policy=policy,
        task_router=task_router,
    )


class EventBroker:
    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self._subscribers: set[asyncio.Queue[Event]] = set()

    def subscribe(self) -> asyncio.Queue[Event]:
        queue: asyncio.Queue[Event] = asyncio.Queue()
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[Event]) -> None:
        self._subscribers.discard(queue)

    def publish(self, event: Event) -> None:
        for queue in list(self._subscribers):
            self._loop.call_soon_threadsafe(queue.put_nowait, event)


class ManagedConversation:

    def __init__(
        self,
        conversation: Conversation,
        sandbox: LocalSandbox,
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
        self.lock = asyncio.Lock()
        self.persist_hook: PersistHook = lambda *_: None

    def on_event(self, event: Event) -> None:
        self._seq += 1
        self._maybe_set_title(event)
        self.persist_hook(self, event, self._seq)
        self.broker.publish(event)

    def set_model(self, model: str) -> None:
        self.conversation.agent.llm.model = model

    def _maybe_set_title(self, event: Event) -> None:
        if self.title is not None:
            return
        if not (isinstance(event, MessageEvent) and event.role == "user"):
            return
        text = event.text.strip()
        snippet = text.splitlines()[0][:60] if text else ""
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
        response = self.conversation.agent.llm.complete(
            [
                {"role": "system", "content": _TITLE_SYSTEM},
                {"role": "user", "content": transcript},
            ]
        )
        text = (response.text or "").strip().strip('"').strip()
        snippet = text.splitlines()[0][:60] if text else ""
        if not snippet:
            return None
        base = self.repo.split("/")[-1] if self.repo else None
        return f"{base}: {snippet}" if base else snippet

    def _title_transcript(self) -> str:
        lines: list[str] = []
        for e in self.conversation.events:
            if isinstance(e, MessageEvent) and e.role in ("user", "assistant"):
                text = e.text.strip()
                if text:
                    lines.append(f"{e.role}: {text[:500]}")
        return "\n".join(lines[:12])

    def bootstrap(self) -> None:
        if not self.repo:
            return
        try:
            worktree = self._workspaces.prepare(
                self.conversation.id, self.repo, self.branch, self._token
            )
        except WorkspaceError as exc:
            self.conversation.add_event(
                ErrorEvent(message=f"workspace setup failed: {exc}")
            )
            self.conversation.status = Status.ERROR
            return
        self.sandbox.set_working_dir(worktree)


class ConversationManager:

    def __init__(
        self,
        settings: Settings,
        data_dir: Path = Path("data"),
    ) -> None:
        self._settings = settings
        self._workspaces = WorkspaceManager(data_dir)
        self._conversations: dict[str, ManagedConversation] = {}
        self._persist_hook: PersistHook = lambda *_: None

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
    ) -> ManagedConversation:
        cid = uuid.uuid4().hex[:8]
        if repo:
            ws = str(self._workspaces.worktree_dir(cid))
        else:
            ws = workspace_dir or self._settings.workspace_dir
        managed = self._build(cid, ws, confirm_mode, user_id, repo, branch, token)
        return managed

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
    ) -> ManagedConversation:
        ws = workspace_dir or self._settings.workspace_dir
        managed = self._build(cid, ws, "risky", user_id, repo, branch, token)
        managed.conversation.events = events
        managed.conversation.plan = Plan.model_validate(plan) if plan else None
        managed.conversation.implementing_plan = implementing_plan
        managed.title = title
        managed._ai_titled = managed.user_turns() >= AI_TITLE_AFTER_TURNS
        managed.pr_number = pr_number
        managed.pr_url = pr_url
        managed._seq = len(events)
        try:
            managed.conversation.status = Status(status)
        except ValueError:
            managed.conversation.status = Status.IDLE
        return managed

    def _build(
        self,
        cid: str,
        workspace_dir: str,
        confirm_mode: ConfirmMode,
        user_id: uuid.UUID,
        repo: str | None,
        branch: str | None,
        token: str | None,
    ) -> ManagedConversation:
        loop = asyncio.get_running_loop()
        sandbox = LocalSandbox(workspace_dir)
        conversation = Conversation(
            agent=_build_agent(self._settings, repo, branch),
            sandbox=sandbox,
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
