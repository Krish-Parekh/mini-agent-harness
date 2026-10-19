from __future__ import annotations

import os
import subprocess

from backend.runtime.pulls import commit_and_push
from miniagent.sandbox.base import CommandResult, Sandbox
from miniagent.sandbox.workspace import GIT_TOKEN_ENV, clone_repo, git_auth

SENTINEL = "ghs_SENTINELTOKEN0123456789"


class RecordingSandbox(Sandbox):
    provider = "recording"

    def __init__(self) -> None:
        self.workspace_dir = "/w"
        self.calls: list[tuple[str, dict | None]] = []

    def run_command(self, command, timeout=30, env=None):
        self.calls.append((command, env))
        return CommandResult(stdout="", stderr="", exit_code=0)

    def write_file(self, path, content): ...
    def read_file(self, path): return ""
    def list_files(self, path): return []
    def close(self): ...


def test_token_only_travels_in_env_for_clone() -> None:
    box = RecordingSandbox()
    clone_repo(box, "octo/repo", "main", SENTINEL, "miniagent/abc")
    assert all(SENTINEL not in command for command, _ in box.calls)
    clone_command, clone_env = box.calls[0]
    assert "https://github.com/octo/repo.git" in clone_command
    assert clone_env == {GIT_TOKEN_ENV: SENTINEL}
    assert box.calls[1] == ("git checkout --quiet -B miniagent/abc", None)


def test_token_only_travels_in_env_for_push() -> None:
    box = RecordingSandbox()
    commit_and_push(box, "octo/repo", "miniagent/abc", SENTINEL, "msg")
    assert all(SENTINEL not in command for command, _ in box.calls)
    push_command, push_env = box.calls[-1]
    assert push_command.endswith("push --force https://github.com/octo/repo.git HEAD:miniagent/abc")
    assert push_env == {GIT_TOKEN_ENV: SENTINEL}


def test_no_token_means_no_helper() -> None:
    assert git_auth(None) == ("", None)


def test_credential_helper_answers_git_with_the_env_token() -> None:
    auth, env = git_auth(SENTINEL)
    result = subprocess.run(
        f"git {auth} credential fill",
        shell=True,
        input="protocol=https\nhost=github.com\n\n",
        capture_output=True,
        text=True,
        env={**os.environ, **env, "GIT_TERMINAL_PROMPT": "0"},
    )
    assert "username=x-access-token" in result.stdout
    assert f"password={SENTINEL}" in result.stdout
