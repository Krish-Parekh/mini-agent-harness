from __future__ import annotations

import asyncio
import subprocess
from types import SimpleNamespace

import httpx
import pytest

from backend.runtime import pulls
from backend.runtime.manager import EventBroker, PrDraft
from backend.schemas import PrProgress
from backend.service.conversation import ConversationService
from miniagent.sandbox.local import LocalSandbox


def _client(handler):
    real = httpx.AsyncClient

    def make(**kwargs):
        return real(transport=httpx.MockTransport(handler), **kwargs)

    return make


async def test_an_open_pr_for_the_branch_is_reused(monkeypatch):
    posted: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path.endswith("/pulls"):
            assert request.url.params["head"] == "octo:miniagent/c1"
            return httpx.Response(200, json=[{"number": 7, "html_url": "https://pr/7"}])
        posted.append(request.url.path)
        return httpx.Response(201, json={"number": 8, "html_url": "https://pr/8"})

    monkeypatch.setattr(pulls.httpx, "AsyncClient", _client(handler))

    pr = await pulls.create_pull_request("octo/repo", "miniagent/c1", "main", "t", "T", "B")

    assert pr["number"] == 7
    assert posted == []


async def test_a_pr_is_opened_when_none_exists(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json=[])
        assert request.method == "POST"
        return httpx.Response(201, json={"number": 8, "html_url": "https://pr/8"})

    monkeypatch.setattr(pulls.httpx, "AsyncClient", _client(handler))

    pr = await pulls.create_pull_request("octo/repo", "miniagent/c1", "main", "t", "T", "B")

    assert pr["number"] == 8


def test_the_staged_diff_and_template_are_read_from_the_checkout(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "pull_request_template.md").write_text("## Summary\n")
    (tmp_path / "app.py").write_text("print('hi')\n")
    sandbox = LocalSandbox(str(tmp_path))

    diff = pulls.staged_diff(sandbox)

    assert "app.py" in diff and "print('hi')" in diff
    assert pulls.pr_template(sandbox) == "## Summary\n"


class Managed:
    def __init__(self, broker: EventBroker) -> None:
        self.conversation = SimpleNamespace(id="c1")
        self.broker = broker
        self.sandbox = object()
        self.repo = "octo/repo"
        self.branch = "main"
        self.pr_number = None
        self.pr_url = None

    def draft_pr(self, diff: str, template: str | None) -> PrDraft:
        return PrDraft(commit_message="Add login", title="Add login page", body="Adds it.")


async def test_creating_a_pr_reports_each_step_and_uses_the_draft(monkeypatch):
    broker = EventBroker(asyncio.get_running_loop())
    queue = broker.subscribe()
    managed = Managed(broker)
    calls: dict = {}
    monkeypatch.setattr(pulls, "staged_diff", lambda sandbox: "diff")
    monkeypatch.setattr(pulls, "pr_template", lambda sandbox: None)
    monkeypatch.setattr(
        pulls, "commit_and_push", lambda *args: calls.setdefault("message", args[-1])
    )

    async def fake_create(repo, head, base, token, title, body):
        calls["title"], calls["body"] = title, body
        return {"number": 3, "html_url": "https://pr/3"}

    monkeypatch.setattr(pulls, "create_pull_request", fake_create)
    repo = SimpleNamespace(set_pr=lambda *a: asyncio.sleep(0))
    service = ConversationService(manager=None, repository=repo, connections=None)
    service.info = lambda m: m.pr_number

    assert await service.create_pr(managed, "token") == 3
    await asyncio.sleep(0)

    steps = []
    while not queue.empty():
        steps.append(queue.get_nowait().step)
    assert steps == ["drafting", "pushing", "opening", "done"]
    assert calls["message"] == "Add login"
    assert calls["title"] == "Add login page"
    assert calls["body"].startswith("Adds it.")


async def test_a_failed_pr_reports_failure(monkeypatch):
    broker = EventBroker(asyncio.get_running_loop())
    queue = broker.subscribe()
    def broken(sandbox):
        raise RuntimeError("boom")

    monkeypatch.setattr(pulls, "staged_diff", broken)
    service = ConversationService(manager=None, repository=None, connections=None)

    with pytest.raises(RuntimeError):
        await service.create_pr(Managed(broker), "token")
    await asyncio.sleep(0)

    steps = [queue.get_nowait() for _ in range(queue.qsize())]
    assert [s.step for s in steps if isinstance(s, PrProgress)] == ["drafting", "failed"]
