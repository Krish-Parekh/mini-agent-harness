from __future__ import annotations

import base64
import json
import re
import subprocess
import threading
import uuid
from dataclasses import dataclass, field

import httpx

IMAGE = "miniagent-sandbox:latest"


@dataclass
class _Sandbox:
    id: str
    container: str
    body: dict
    polls_until_running: int = 2
    state: str = "creating"


@dataclass
class FakeSpace:
    """SPACE's documented M1 HTTP protocol, with commands executed for real in
    a Docker container. Tracks what the client sent so tests can assert on it."""

    token: str = "mgmt-token"
    email: str = "root@local"
    password: str = "password"
    sandboxes: dict[str, _Sandbox] = field(default_factory=dict)
    create_keys: dict[str, str] = field(default_factory=dict)
    operations: dict[str, dict] = field(default_factory=dict)
    sessions: dict[str, dict] = field(default_factory=dict)
    requests: list[httpx.Request] = field(default_factory=list)
    reject_next_token: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def close(self) -> None:
        for sbx in self.sandboxes.values():
            subprocess.run(["docker", "rm", "-f", sbx.container], capture_output=True)

    def _operation(self, state: str = "succeeded") -> str:
        op = f"op_{uuid.uuid4().hex}"
        self.operations[op] = {"state": state, "polls": 1}
        return op

    def handle(self, request: httpx.Request) -> httpx.Response:
        with self._lock:
            self.requests.append(request)
        path = request.url.path
        if request.url.port == 8090:
            return self._events(request, path)
        if path == "/auth/v1/sessions" and request.method == "POST":
            body = json.loads(request.content)
            if body == {"email": self.email, "password": self.password}:
                return httpx.Response(200, json={"token": self.token})
            return httpx.Response(401, json={"code": "unauthenticated"})
        if request.headers.get("Authorization") != f"Bearer {self.token}" or self.reject_next_token:
            self.reject_next_token = False
            return httpx.Response(401, json={"code": "unauthenticated"})
        if path == "/v1/sandboxes" and request.method == "POST":
            return self._create(request)
        if m := re.fullmatch(r"/v1/operations/(op_\w+)", path):
            op = self.operations[m[1]]
            if op["polls"] > 0:
                op["polls"] -= 1
                return httpx.Response(200, json={"state": "running"})
            return httpx.Response(200, json={"state": op["state"]})
        if m := re.fullmatch(r"/v1/sandboxes/(sbx_\w+)(.*)", path):
            sbx = self.sandboxes.get(m[1])
            if sbx is None:
                return httpx.Response(404, json={"code": "not_found"})
            return self._sandbox_route(request, sbx, m[2])
        return httpx.Response(404, json={"code": "not_found"})

    def _create(self, request: httpx.Request) -> httpx.Response:
        key = request.headers.get("Idempotency-Key")
        if not key:
            return httpx.Response(400, json={"code": "idempotency_key_required"})
        body = json.loads(request.content)
        if key in self.create_keys:
            sbx = self.sandboxes[self.create_keys[key]]
            return httpx.Response(202, json={"sandbox_id": sbx.id, "operation_id": self._operation()})
        sandbox_id = f"sbx_{uuid.uuid4().hex}"
        container = subprocess.run(
            ["docker", "run", "-d", "--init", "--label", "miniagent.fake-space=1", IMAGE, "sleep", "infinity"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        self.sandboxes[sandbox_id] = _Sandbox(id=sandbox_id, container=container, body=body)
        self.create_keys[key] = sandbox_id
        return httpx.Response(202, json={"sandbox_id": sandbox_id, "operation_id": self._operation()})

    def _sandbox_route(self, request: httpx.Request, sbx: _Sandbox, rest: str) -> httpx.Response:
        if rest == "" and request.method == "GET":
            if sbx.polls_until_running > 0:
                sbx.polls_until_running -= 1
            elif sbx.state == "creating":
                sbx.state = "running"
            return httpx.Response(200, json={"sandbox_id": sbx.id, "state": sbx.state})
        if rest == "" and request.method == "DELETE":
            if not request.headers.get("Idempotency-Key"):
                return httpx.Response(400, json={"code": "idempotency_key_required"})
            subprocess.run(["docker", "rm", "-f", sbx.container], capture_output=True)
            del self.sandboxes[sbx.id]
            return httpx.Response(202, json={"sandbox_id": sbx.id, "operation_id": self._operation()})
        if rest == ":wake" and request.method == "POST":
            sbx.state, sbx.polls_until_running = "creating", 1
            return httpx.Response(202, json={"sandbox_id": sbx.id, "operation_id": self._operation()})
        if rest.startswith("/processes") and request.method == "GET":
            return httpx.Response(200, json={"data": [], "next_cursor": None})
        if rest == "/commands" and request.method == "POST":
            if not request.headers.get("Idempotency-Key"):
                return httpx.Response(400, json={"code": "idempotency_key_required"})
            if sbx.state != "running":
                return httpx.Response(409, json={"code": "sandbox_not_running"})
            session = f"proc_{uuid.uuid4().hex}"
            attach_token = uuid.uuid4().hex
            self.sessions[session] = {"sbx": sbx, "body": json.loads(request.content), "token": attach_token}
            return httpx.Response(201, json={
                "session_id": session, "process_id": session, "sandbox_id": sbx.id,
                "attach": {"events_url": f"/v1/sessions/{session}/events", "token": attach_token},
            })
        return httpx.Response(404, json={"code": "not_found"})

    def _events(self, request: httpx.Request, path: str) -> httpx.Response:
        m = re.fullmatch(r"/v1/sessions/(proc_\w+)/events", path)
        session = self.sessions.pop(m[1], None) if m else None
        if session is None:
            return httpx.Response(404, json={"code": "not_found"})
        if request.headers.get("Authorization") != f"Bearer {session['token']}":
            return httpx.Response(401, json={"code": "bad_attach_token"})
        body = session["body"]
        args = ["docker", "exec", "-i"]
        for k, v in (body.get("env") or {}).items():
            args += ["-e", f"{k}={v}"]
        if body.get("cwd"):
            args += ["-w", body["cwd"]]
        proc = subprocess.run(args + [session["sbx"].container, *body["command"]], capture_output=True)
        frames = [{"type": "attached"}, {"type": "process_started", "pid": 1}]
        if proc.stdout:
            frames.append({"type": "stdout", "seq": 1, "data_base64": base64.b64encode(proc.stdout).decode()})
        if proc.stderr:
            frames.append({"type": "stderr", "seq": 2, "data_base64": base64.b64encode(proc.stderr).decode()})
        frames.append({"type": "process_exited", "exit_code": proc.returncode, "status": "exited"})
        payload = "".join(f"event: frame\ndata: {json.dumps(f)}\n\n" for f in frames)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=payload.encode())
