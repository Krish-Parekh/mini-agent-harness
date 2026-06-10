from __future__ import annotations

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


class FileEditTool(Tool):
    name = "file_edit"
    description = (
        "View, create, or edit a file in the workspace. "
        "command='view' returns the file's raw text exactly as stored (no line "
        "numbers); pass view_range=[start, end] (1-based, end -1 = EOF) for a "
        "slice. command='create' writes content to a new file. "
        "command='str_replace' replaces a unique old_str with new_str — old_str "
        "must match the raw file bytes exactly (copy from view output, never "
        "include line-number prefixes) and appear exactly once, so include "
        "enough surrounding context to be unique."
    )
    action_type = FileEditAction
    observation_type = FileEditObservation

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
        sandbox.write_file(action.path, action.content)
        return FileEditObservation(output=f"Created {action.path}")

    def _str_replace(
        self, action: FileEditAction, sandbox: Sandbox
    ) -> FileEditObservation:
        if action.old_str is None:
            return self._fail("str_replace requires 'old_str'")
        try:
            content = sandbox.read_file(action.path)
        except FileNotFoundError:
            return self._fail(f"File not found: {action.path}")

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
        return FileEditObservation(output=f"Edited {action.path}")

    @staticmethod
    def _fail(message: str) -> FileEditObservation:
        return FileEditObservation(output=message, error=True)
