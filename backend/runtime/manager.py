from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from typing import Callable

from miniagent.agent import Agent
from miniagent.classification import TaskClassifier
from miniagent.config import Settings
from miniagent.confirm import ConfirmMode, ConfirmPolicy
from miniagent.conversation import Conversation, Status
from miniagent.events import ActionEvent, ErrorEvent, Event, MessageEvent, ObservationEvent
from miniagent.llm import LLM
from miniagent.policy import PolicyClassifier
from miniagent.prompts import DISTILL_SKILL_PROMPT
from miniagent.sandbox.local import LocalSandbox
from miniagent.sandbox.workspace import WorkspaceError
from miniagent.text import clip
from backend.runtime.workspaces import WorkspaceManager
from miniagent.tools.bash import BashTool
from miniagent.tools.base import ToolRegistry
from miniagent.tools.file_edit import FileEditTool
from miniagent.tools.finish import FinishTool
from miniagent.tools.ask import AskUserTool
from miniagent.tools.fanout import FanoutTool
from miniagent.tools.plan import Plan, PresentPlanTool, UpdatePlanTool
from miniagent.tools.skill import ReadSkillTool
from miniagent.skills import SkillLibrary

PersistHook = Callable[["ManagedConversation", Event, int], None]

AI_TITLE_AFTER_TURNS = 4
_SKILL_TRANSCRIPT_BUDGET = 16_000

_TITLE_SYSTEM = (
    "You write a short, specific title for a coding conversation. "
    "Reply with the title only: 3 to 6 words, no quotes, no trailing "
    "punctuation."
)


def _parse_skill_json(text: str) -> dict | None:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        first_nl = cleaned.find("\n")
        cleaned = cleaned[first_nl + 1 :] if first_nl != -1 else ""
        cleaned = cleaned.strip()
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3].strip()
    try:
        data = json.loads(cleaned)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    decision = data.get("decision")
    if decision == "skip":
        return {"decision": "skip"}
    if decision not in ("create", "update"):
        return None
    if data.get("scope") not in ("repo", "global"):
        return None
    for key in ("name", "description", "body"):
        if not isinstance(data.get(key), str) or not data[key].strip():
            return None
    return data


def _build_agent(
    settings: Settings,
    repo: str | None,
    branch: str | None,
    skills: SkillLibrary | None = None,
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
    tools = ToolRegistry(
        [
            BashTool(),
            FileEditTool(),
            FinishTool(),
            PresentPlanTool(),
            UpdatePlanTool(),
            AskUserTool(),
            *([ReadSkillTool(skills, repo)] if skills is not None else []),
            FanoutTool(llm, repo, branch, skills, policy),
        ]
    )
    return Agent(
        llm=llm,
        tools=tools,
        repo=repo,
        branch=branch,
        skills=skills,
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
    """A live conversation: the agent loop's Conversation + sandbox + broker.

    `on_event` fans each event out to live subscribers and to the persistence
    hook the service installs; it carries no knowledge of how persistence works.
    """

    def __init__(
        self,
        conversation: Conversation,
        sandbox: LocalSandbox,
        broker: EventBroker,
        workspaces: WorkspaceManager,
        repo: str | None = None,
        branch: str | None = None,
        token: str | None = None,
    ) -> None:
        self.conversation = conversation
        self.sandbox = sandbox
        self.broker = broker
        self._workspaces = workspaces
        self.repo = repo
        self.branch = branch
        self._token = token
        self.title: str | None = None
        self._ai_titled = False
        self._distilled = False
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
        """Switch the model for subsequent agent steps (LLM reads it per call)."""
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
        """Concise title from the transcript. Blocking (litellm) — call in a
        worker thread."""
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

    def _skill_transcript(self) -> str:
        lines: list[str] = []
        for event in self.conversation.events:
            if isinstance(event, MessageEvent):
                text = event.text.strip()
                if text:
                    lines.append(f"{event.role}: {text}")
            elif isinstance(event, ActionEvent):
                lines.append(f"tool {event.tool_name}: {json.dumps(event.arguments)}")
            elif isinstance(event, ObservationEvent):
                status = "ERROR" if event.error else "OK"
                lines.append(f"result[{status}]: {event.content}")
            elif isinstance(event, ErrorEvent):
                lines.append(f"error: {event.message}")
        return clip("\n".join(lines), _SKILL_TRANSCRIPT_BUDGET)

    def distill_skill(self, library: SkillLibrary) -> str | None:
        """Distill one reusable skill from this finished session, if warranted.

        Blocking (litellm) — call in a worker thread. Returns the slug written,
        or None when the distiller chose to skip or produced invalid output."""
        transcript = self._skill_transcript()
        if not transcript:
            return None
        existing = library.index(self.repo)
        existing_block = (
            "\n".join(f"- {r.name} ({r.scope}): {r.description}" for r in existing)
            or "(none)"
        )
        response = self.conversation.agent.llm.complete(
            [
                {"role": "system", "content": DISTILL_SKILL_PROMPT},
                {
                    "role": "user",
                    "content": f"# Existing skills\n{existing_block}\n\n"
                    f"# Session transcript\n{transcript}",
                },
            ]
        )
        data = _parse_skill_json(response.text or "")
        if data is None or data.get("decision") == "skip":
            return None
        library.write(
            name=data["name"],
            description=data["description"],
            body=data["body"],
            scope=data["scope"],
            repo=self.repo,
        )
        return SkillLibrary.slugify(data["name"])

    def bootstrap(self) -> None:
        """Set up this conversation's isolated worktree (cloning the repo once
        if needed) before the agent runs. Runs in a worker thread."""
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
    """In-memory registry and factory of live conversations. No persistence."""

    def __init__(
        self,
        settings: Settings,
        data_dir: Path = Path("data"),
        skills: SkillLibrary | None = None,
    ) -> None:
        self._settings = settings
        self._workspaces = WorkspaceManager(data_dir)
        self.skills = skills
        self._conversations: dict[str, ManagedConversation] = {}
        self._persist_hook: PersistHook = lambda *_: None

    def set_persist_hook(self, hook: PersistHook) -> None:
        self._persist_hook = hook

    def create(
        self,
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
        managed = self._build(cid, ws, confirm_mode, repo, branch, token)
        return managed

    def release_workspace(self, cid: str, repo: str | None) -> None:
        self._workspaces.release(cid, repo)

    def register_revived(
        self,
        *,
        cid: str,
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
    ) -> ManagedConversation:
        ws = workspace_dir or self._settings.workspace_dir
        managed = self._build(cid, ws, "risky", repo, branch, None)
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
        repo: str | None,
        branch: str | None,
        token: str | None,
    ) -> ManagedConversation:
        loop = asyncio.get_running_loop()
        sandbox = LocalSandbox(workspace_dir)
        conversation = Conversation(
            agent=_build_agent(self._settings, repo, branch, self.skills),
            sandbox=sandbox,
            confirm_policy=ConfirmPolicy(confirm_mode),
            id=cid,
        )
        managed = ManagedConversation(
            conversation, sandbox, EventBroker(loop), self._workspaces, repo, branch, token
        )
        managed.persist_hook = self._persist_hook
        conversation.on_event = managed.on_event
        self._conversations[cid] = managed
        return managed

    def get(self, cid: str) -> ManagedConversation | None:
        return self._conversations.get(cid)

    def remove(self, cid: str) -> ManagedConversation | None:
        return self._conversations.pop(cid, None)
