from __future__ import annotations

from typing import Literal

from miniagent.sandbox.base import Sandbox
from miniagent.schema import Action, Observation
from miniagent.tools.base import Tool


class FileEditAction(Action):
    command: Literal["view", "create", "str_replace"]
    path: str
    content: str | None = None
    old_str: str | None = None
    new_str: str | None = None


class FileEditObservation(Observation):
    output: str
    error: bool = False

    def to_llm_text(self) -> str:
        return self.output


class FileEditTool(Tool):
    name = "file_edit"
    description = (
        "View, create, or edit a file in the workspace. "
        "command='view' reads a file; "
        "command='create' writes content to a new file; "
        "command='str_replace' replaces a unique old_str with new_str."
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
        lines = content.splitlines()
        numbered = "\n".join(f"{i:>6}\t{line}" for i, line in enumerate(lines, 1))
        return FileEditObservation(output=numbered or "(empty file)")

    def _create(self, action: FileEditAction, sandbox: Sandbox) -> FileEditObservation:
        if action.content is None:
            return self._fail("create requires 'content'")
        sandbox.write_file(action.path, action.content)
        return FileEditObservation(output=f"Created {action.path}")

    def _str_replace(self, action: FileEditAction, sandbox: Sandbox) -> FileEditObservation:
        if action.old_str is None:
            return self._fail("str_replace requires 'old_str'")
        try:
            content = sandbox.read_file(action.path)
        except FileNotFoundError:
            return self._fail(f"File not found: {action.path}")

        count = content.count(action.old_str)
        if count == 0:
            return self._fail("old_str not found in file")
        if count > 1:
            return self._fail(f"old_str is not unique ({count} matches); add more context")

        new_content = content.replace(action.old_str, action.new_str or "")
        sandbox.write_file(action.path, new_content)
        return FileEditObservation(output=f"Edited {action.path}")

    @staticmethod
    def _fail(message: str) -> FileEditObservation:
        return FileEditObservation(output=message, error=True)
