from __future__ import annotations

import hashlib
import posixpath
from typing import Literal

from miniagent.sandbox.base import Sandbox
from miniagent.schema import Action, Observation
from miniagent.tools.base import Tool
from miniagent.tools.file_edit_match import (
    apply_str_replace,
    diagnose_multiple,
    diagnose_no_match,
)


class FileEditAction(Action):
    command: Literal["view", "create", "str_replace"]
    path: str
    content: str | None = None
    old_str: str | None = None
    new_str: str | None = None
    view_range: list[int] | None = None


class FileEditObservation(Observation):
    output: str
    error: bool = False

    def to_llm_text(self) -> str:
        return self.output


class FileObservations:
    def __init__(self) -> None:
        self._hashes: dict[str, str] = {}

    @staticmethod
    def key(path: str, sandbox: Sandbox) -> str:
        if not posixpath.isabs(path):
            path = posixpath.join(sandbox.workspace_dir, path)
        return posixpath.normpath(path)

    @staticmethod
    def digest(content: str) -> str:
        return hashlib.sha256(content.encode()).hexdigest()

    def record(self, path: str, sandbox: Sandbox, content: str) -> None:
        self._hashes[self.key(path, sandbox)] = self.digest(content)

    def problem(self, path: str, sandbox: Sandbox, content: str) -> str | None:
        seen = self._hashes.get(self.key(path, sandbox))
        if seen is None:
            return f"File not viewed yet: view {path} first, then retry."
        if seen != self.digest(content):
            return (
                f"{path} changed since you last viewed it (another edit or the "
                "user). View it again, then retry."
            )
        return None


class FileEditTool(Tool):
    name = "file_edit"
    description = (
        "View, create, or edit a file in the workspace. "
        "command='view' returns the file's raw text exactly as stored (no line "
        "numbers); pass view_range=[start, end] (1-based, end -1 = EOF) for a "
        "slice. command='create' writes content to a new file (overwriting an "
        "existing file requires viewing it first). "
        "command='str_replace' replaces a unique old_str with new_str; old_str "
        "must match the raw file bytes exactly (copy from view output, never "
        "include line-number prefixes) and appear exactly once, so include "
        "enough surrounding context to be unique. Edit only files you have viewed "
        "in this conversation; if a file changed since your last view, view it "
        "again before editing."
    )
    action_type = FileEditAction
    observation_type = FileEditObservation

    def __init__(self) -> None:
        self.observed = FileObservations()

    def execute(self, action: FileEditAction, sandbox: Sandbox) -> FileEditObservation:
        if action.command == "view":
            return self._view(action, sandbox)
        if action.command == "create":
            return self._create(action, sandbox)
        return self._str_replace(action, sandbox)

    def _view(self, action: FileEditAction, sandbox: Sandbox) -> FileEditObservation:
        try:
            content = sandbox.read_file(action.path)
        except FileNotFoundError:
            return self._fail(f"File not found: {action.path}")
        self.observed.record(action.path, sandbox, content)
        if not content:
            return FileEditObservation(output="(empty file)")
        if action.view_range is None:
            return FileEditObservation(output=content)
        return self._view_slice(action.path, content, action.view_range)

    def _view_slice(
        self, path: str, content: str, view_range: list[int]
    ) -> FileEditObservation:
        if len(view_range) != 2:
            return self._fail("view_range must be [start, end]")
        lines = content.splitlines()
        start, end = view_range
        if end == -1:
            end = len(lines)
        if start < 1 or start > len(lines) or end < start:
            return self._fail(
                f"view_range [{view_range[0]}, {view_range[1]}] is out of bounds; "
                f"file has {len(lines)} lines"
            )
        end = min(end, len(lines))
        body = "\n".join(lines[start - 1 : end])
        return FileEditObservation(output=f"# lines {start}-{end} of {path}\n{body}")

    def _create(self, action: FileEditAction, sandbox: Sandbox) -> FileEditObservation:
        if action.content is None:
            return self._fail("create requires 'content'")
        try:
            existing = sandbox.read_file(action.path)
        except FileNotFoundError:
            existing = None
        if existing is not None and self.observed.problem(
            action.path, sandbox, existing
        ):
            return self._fail(
                f"{action.path} already exists. View it and use str_replace, or "
                "view it and create again to overwrite."
            )
        sandbox.write_file(action.path, action.content)
        self.observed.record(action.path, sandbox, action.content)
        verb = "Overwrote" if existing is not None else "Created"
        return FileEditObservation(output=f"{verb} {action.path}")

    def _str_replace(
        self, action: FileEditAction, sandbox: Sandbox
    ) -> FileEditObservation:
        if action.old_str is None:
            return self._fail("str_replace requires 'old_str'")
        try:
            content = sandbox.read_file(action.path)
        except FileNotFoundError:
            return self._fail(f"File not found: {action.path}")
        problem = self.observed.problem(action.path, sandbox, content)
        if problem:
            return self._fail(problem)

        new_str = action.new_str or ""
        new_content, count = apply_str_replace(content, action.old_str, new_str)
        if count == 0:
            return self._fail(
                diagnose_no_match(content, action.old_str, new_str, action.path)
            )
        if count > 1:
            return self._fail(
                diagnose_multiple(content, action.old_str, action.path, count)
            )

        sandbox.write_file(action.path, new_content)
        self.observed.record(action.path, sandbox, new_content)
        return FileEditObservation(output=f"Edited {action.path}")

    @staticmethod
    def _fail(message: str) -> FileEditObservation:
        return FileEditObservation(output=message, error=True)
