from __future__ import annotations

import base64
import json
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

from miniagent.sandbox.base import TIMEOUT_EXIT_CODE, SandboxError, SandboxExpired
from miniagent.sandbox.shell import RawResult, ShellSandbox

_REQUEST_TIMEOUT_S = 30
_READY_TIMEOUT_S = 300
_DELETE_TIMEOUT_S = 60
_TERMINAL_OPERATION = {"failed", "canceled", "expired"}
_DEAD_SANDBOX = {"failed", "deleting", "deleted"}
_SLEEPING_SANDBOX = {"paused", "suspended", "stopped"}
_LOOPBACK = {"127.0.0.1", "localhost", "::1"}


@dataclass(frozen=True)
class SpaceConfig:
    api_url: str
    data_plane_url: str
    template: str = "code-runtime:latest"
    token: str = ""
    email: str = ""
    password: str = ""
    allow_internet: bool = True
    egress_profiles: str = ""
    vcpu: int | None = None
    memory_mib: int | None = None


def _origin(url: str, name: str) -> str:
    parsed = urlsplit(url.rstrip("/"))
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"{name} must be an http(s) origin")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError(f"{name} must not carry credentials, a query or a fragment")
    if parsed.scheme == "http" and parsed.hostname not in _LOOPBACK:
        raise ValueError(f"{name} requires https; plain http is only allowed on loopback")
    return url.rstrip("/")


class SpaceSandbox(ShellSandbox):
    """Perplexity SPACE through its native API, using only M1-supported routes:
    sandboxes, operations, commands and their event streams. Files go through
    the shell because the native file routes are still incubating."""

    provider = "space"

    def __init__(
        self,
        config: SpaceConfig,
        *,
        workspace_dir: str = "/home/user/workspace",
        sandbox_id: str | None = None,
        name: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        super().__init__(workspace_dir)
        self.sandbox_id = sandbox_id
        self._config = config
        self._name = name
        self._api_url = _origin(config.api_url, "SPACE API URL")
        self._data_url = _origin(config.data_plane_url, "SPACE data-plane URL")
        # Tokens must never ride an inherited proxy or follow a redirect.
        self._http = httpx.Client(
            transport=transport,
            trust_env=False,
            follow_redirects=False,
            timeout=_REQUEST_TIMEOUT_S,
        )
        self._token = config.token

    # --- management API ---------------------------------------------------

    def _login(self) -> None:
        if not (self._config.email and self._config.password):
            raise SandboxError("SPACE token rejected and no login credentials are set")
        response = self._http.post(
            f"{self._api_url}/auth/v1/sessions",
            json={"email": self._config.email, "password": self._config.password},
        )
        if response.status_code != 200:
            raise SandboxError(f"SPACE login failed: HTTP {response.status_code}")
        self._token = response.json().get("token", "")
        if not self._token:
            raise SandboxError("SPACE login returned no token")

    def _api(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        *,
        key: str | None = None,
        headers: dict[str, str] | None = None,
        allow: tuple[int, ...] = (),
    ) -> httpx.Response:
        if not self._token:
            self._login()
        for attempt in range(2):
            request_headers = {"Authorization": f"Bearer {self._token}", "Accept": "application/json"}
            if key:
                request_headers["Idempotency-Key"] = key
            request_headers.update(headers or {})
            try:
                response = self._http.request(
                    method, f"{self._api_url}{path}", json=body, headers=request_headers
                )
            except httpx.HTTPError as exc:
                raise SandboxError(f"SPACE {method} {path}: {exc}") from exc
            if response.status_code == 401 and attempt == 0 and self._config.email:
                self._login()
                continue
            if response.is_success or response.status_code in allow:
                return response
            raise SandboxError(
                f"SPACE {method} {path}: HTTP {response.status_code}: {response.text[:300]}"
            )
        raise SandboxError(f"SPACE {method} {path}: unauthorized")

    def _wait_operation(self, operation_id: str, deadline_s: float) -> None:
        end = time.monotonic() + deadline_s
        while time.monotonic() < end:
            state = self._api("GET", f"/v1/operations/{operation_id}").json()
            status = state.get("state")
            if status == "succeeded":
                return
            if status in _TERMINAL_OPERATION:
                detail = state.get("terminal_error") or state.get("terminal_error_code") or status
                raise SandboxError(f"SPACE operation {operation_id} {status}: {detail}")
            time.sleep(1)
        raise SandboxError(f"SPACE operation {operation_id} did not finish in {deadline_s:.0f}s")

    def _sandbox_state(self) -> str | None:
        response = self._api("GET", f"/v1/sandboxes/{self.sandbox_id}", allow=(404,))
        if response.status_code == 404:
            return None
        return response.json().get("state")

    def _wait_running(self, deadline_s: float) -> None:
        end = time.monotonic() + deadline_s
        while time.monotonic() < end:
            state = self._sandbox_state()
            if state == "running":
                self._api("GET", f"/v1/sandboxes/{self.sandbox_id}/processes?limit=1")
                return
            if state is None or state in _DEAD_SANDBOX:
                raise SandboxExpired(f"SPACE sandbox {self.sandbox_id} is {state or 'gone'}")
            time.sleep(1)
        raise SandboxError(f"SPACE sandbox {self.sandbox_id} did not become ready")

    def _create_body(self) -> dict:
        body: dict = {"template": self._config.template}
        if self._name:
            body["name"] = self._name
            body["metadata"] = {"app": "miniagent", "conversation": self._name}
        resources = {
            k: v
            for k, v in (("vcpu", self._config.vcpu), ("memory_mib", self._config.memory_mib))
            if v
        }
        if resources:
            body["resources"] = resources
        if self._config.allow_internet:
            # Incubating field. The default template policy denies all egress,
            # and git needs github.com. TLS interception would break git.
            body["network_policy"] = {
                "version": "v1",
                "egress": {"default_action": "allow", "allow": [], "deny": []},
                "tls_interception": "off",
            }
        return body

    def _open(self) -> None:
        if self.sandbox_id:
            state = self._sandbox_state()
            if state is None or state in _DEAD_SANDBOX:
                raise SandboxExpired(f"SPACE sandbox {self.sandbox_id} is {state or 'gone'}")
            if state in _SLEEPING_SANDBOX:
                wake = self._api(
                    "POST", f"/v1/sandboxes/{self.sandbox_id}:wake", key=str(uuid.uuid4())
                ).json()
                if wake.get("operation_id"):
                    self._wait_operation(wake["operation_id"], _READY_TIMEOUT_S)
            self._wait_running(_READY_TIMEOUT_S)
            return
        headers = (
            {"X-Space-Egress-Profiles": self._config.egress_profiles}
            if self._config.egress_profiles
            else None
        )
        # A stable key makes a retried create return the same sandbox.
        key = f"miniagent-create-{self._name}" if self._name else str(uuid.uuid4())
        created = self._api(
            "POST", "/v1/sandboxes", self._create_body(), key=key, headers=headers
        ).json()
        self.sandbox_id = created["sandbox_id"]
        self._wait_operation(created["operation_id"], _READY_TIMEOUT_S)
        self._wait_running(_READY_TIMEOUT_S)
        raw = self._run(["mkdir", "-p", self.workspace_dir], 60, None, cwd=None)
        if raw.exit_code != 0:
            raise SandboxError(f"SPACE workspace setup failed: {raw.stderr.strip()}")

    # --- commands ---------------------------------------------------------

    def _exec(self, script, timeout, env) -> RawResult:
        return self._run(["bash", "-c", script], timeout, env, cwd=None)

    def _run(
        self, argv: list[str], timeout: int, env: dict[str, str] | None, *, cwd: str | None
    ) -> RawResult:
        body: dict = {"command": argv, "timeout": f"{int(timeout)}s"}
        if cwd:
            body["cwd"] = cwd
        if env:
            body["env"] = env
        session = self._api(
            "POST", f"/v1/sandboxes/{self.sandbox_id}/commands", body, key=str(uuid.uuid4())
        ).json()
        attach = session.get("attach") or {}
        token = attach.get("token")
        events_url = self._events_url(session.get("session_id", ""), attach.get("events_url", ""))
        if not token:
            raise SandboxError("SPACE command returned no attachment token")
        return self._stream(events_url, token, timeout + 5)

    def _events_url(self, session_id: str, events_url: str) -> str:
        path = f"/v1/sessions/{session_id}/events"
        if events_url not in {path, f"{self._data_url}{path}"}:
            raise SandboxError("SPACE returned an unexpected events URL")
        return f"{self._data_url}{path}"

    def _stream(self, url: str, token: str, read_timeout: int) -> RawResult:
        stdout = bytearray()
        stderr = bytearray()
        headers = {"Authorization": f"Bearer {token}", "Accept": "text/event-stream"}
        try:
            with self._http.stream(
                "GET", url, headers=headers, timeout=httpx.Timeout(_REQUEST_TIMEOUT_S, read=read_timeout)
            ) as response:
                if not response.is_success:
                    response.read()
                    raise SandboxError(
                        f"SPACE attach: HTTP {response.status_code}: {response.text[:300]}"
                    )
                for frame in _sse_frames(response.iter_lines()):
                    kind = frame.get("type")
                    if kind == "stdout":
                        stdout += base64.b64decode(frame["data_base64"])
                    elif kind == "stderr":
                        stderr += base64.b64decode(frame["data_base64"])
                    elif kind == "process_exited":
                        code = frame.get("exit_code")
                        if frame.get("status") == "timed_out":
                            code = TIMEOUT_EXIT_CODE
                        return RawResult(
                            stdout=stdout.decode("utf-8", "replace"),
                            stderr=stderr.decode("utf-8", "replace"),
                            exit_code=code if isinstance(code, int) else -1,
                        )
                    elif kind in {"error", "resync_required"}:
                        raise SandboxError(f"SPACE command stream reported {kind}: {frame}")
        except httpx.ReadTimeout:
            return RawResult(
                stdout=stdout.decode("utf-8", "replace"),
                stderr=stderr.decode("utf-8", "replace"),
                exit_code=TIMEOUT_EXIT_CODE,
            )
        except httpx.HTTPError as exc:
            raise SandboxError(f"SPACE command stream failed: {exc}") from exc
        raise SandboxError("SPACE command stream ended without process_exited")

    # --- lifecycle --------------------------------------------------------

    def close(self) -> None:
        try:
            if self.sandbox_id:
                deleted = self._api(
                    "DELETE", f"/v1/sandboxes/{self.sandbox_id}", key=str(uuid.uuid4()), allow=(404,)
                )
                if deleted.status_code != 404 and deleted.content:
                    operation = deleted.json().get("operation_id")
                    if operation:
                        self._wait_operation(operation, _DELETE_TIMEOUT_S)
        except SandboxError:
            pass
        finally:
            self._http.close()


def _sse_frames(lines: Iterator[str]) -> Iterator[dict]:
    data: list[str] = []
    for line in lines:
        if line == "":
            if data:
                frame = json.loads("\n".join(data))
                data = []
                if isinstance(frame, dict):
                    yield frame
            continue
        field, _, value = line.partition(":")
        if field == "data":
            data.append(value[1:] if value.startswith(" ") else value)
    if data:
        frame = json.loads("\n".join(data))
        if isinstance(frame, dict):
            yield frame
