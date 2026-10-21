from __future__ import annotations

import posixpath
import re
from typing import Literal, Protocol

from miniagent.sandbox.base import Sandbox
from miniagent.schema import Action, Observation
from miniagent.tools.base import Tool

ROOT = "/memories"
USER_DIR = f"{ROOT}/user"
REPO_DIR = f"{ROOT}/repo"
MAX_MEMORY_CHARS = 10_000
MAX_VIEW_CHARS = 16_000
MAX_INDEX_LINES = 200


class MemoryStore(Protocol):
    has_repo: bool

    def load(self) -> dict[str, str]: ...

    def save(self, path: str, content: str) -> None: ...

    def delete(self, path: str) -> None: ...


class MemoryAction(Action):
    command: Literal["view", "create", "str_replace", "insert", "delete", "rename"]
    path: str | None = None
    view_range: list[int] | None = None
    file_text: str | None = None
    old_str: str | None = None
    new_str: str | None = None
    insert_line: int | None = None
    insert_text: str | None = None
    old_path: str | None = None
    new_path: str | None = None


class MemoryObservation(Observation):
    output: str
    error: bool = False

    def to_llm_text(self) -> str:
        return self.output


class _Refused(Exception):
    pass


class MemoryTool(Tool):
    name = "memory"
    description = (
        "Read and write your persistent memory, which is kept across "
        "conversations. /memories/user/ holds notes about the user that apply in "
        "every repository; /memories/repo/ holds notes about the current "
        "repository. Commands: `view` lists a directory or shows a file with line "
        "numbers (optional view_range); `create` creates or overwrites a file "
        "with file_text; `str_replace` replaces a unique old_str with new_str; "
        "`insert` adds insert_text after line insert_line (0 is the top); "
        "`delete` removes a file or directory; `rename` moves old_path to "
        "new_path. Keep one topic per file, update an existing file instead of "
        "adding a duplicate, and delete memories that turn out to be wrong."
    )
    action_type = MemoryAction
    observation_type = MemoryObservation

    def __init__(self, store: MemoryStore) -> None:
        self.store = store

    def execute(self, action: MemoryAction, sandbox: Sandbox) -> MemoryObservation:
        try:
            output = getattr(self, f"_{action.command}")(action, self.store.load())
        except _Refused as exc:
            return MemoryObservation(output=str(exc), error=True)
        return MemoryObservation(output=output)

    def _view(self, action: MemoryAction, files: dict[str, str]) -> str:
        path = self._resolve(action.path)
        if path in files:
            lines = files[path].removesuffix("\n").split("\n")
            start, end = action.view_range or [1, len(lines)]
            end = len(lines) if end == -1 else end
            if not 1 <= start <= end <= len(lines):
                raise _Refused(
                    f"Error: Invalid `view_range` {action.view_range}. "
                    f"The file has {len(lines)} lines."
                )
            numbered = "\n".join(
                f"{number:6d}\t{line}"
                for number, line in enumerate(lines[start - 1 : end], start)
            )
            if len(numbered) > MAX_VIEW_CHARS:
                numbered = (
                    numbered[:MAX_VIEW_CHARS]
                    + "\n[truncated; use view_range to read the rest]"
                )
            return f"Here's the content of {path} with line numbers:\n{numbered}"
        if path not in self._dirs() and not _children(path, files):
            raise _Refused(f"The path {path} does not exist. Please provide a valid path.")
        sizes: dict[str, int] = {entry: 0 for entry in self._dirs() if entry.startswith(path + "/")}
        for file, content in _children(path, files).items():
            parts = file[len(path) + 1 :].split("/")
            for depth in range(1, min(len(parts), 2) + 1):
                entry = f"{path}/{'/'.join(parts[:depth])}"
                sizes[entry] = sizes.get(entry, 0) + len(content.encode())
        total = sum(len(content.encode()) for content in _children(path, files).values())
        listing = [f"{_size(total)}\t{path}"]
        listing += [f"{_size(size)}\t{entry}" for entry, size in sorted(sizes.items())]
        return (
            f"Here're the files and directories up to 2 levels deep in {path}, "
            "excluding hidden items and node_modules:\n" + "\n".join(listing)
        )

    def _create(self, action: MemoryAction, files: dict[str, str]) -> str:
        path = self._file(action.path)
        if _children(path, files):
            raise _Refused(f"Error: {path} is a directory")
        self._save(path, action.file_text or "")
        return f"File created successfully at: {path}"

    def _str_replace(self, action: MemoryAction, files: dict[str, str]) -> str:
        path = self._file(action.path)
        if path not in files:
            raise _Refused(f"Error: The path {path} does not exist. Please provide a valid path.")
        content, old = files[path], action.old_str or ""
        starts = [match.start() for match in re.finditer(re.escape(old), content)] if old else []
        if not starts:
            raise _Refused(
                f"No replacement was performed, old_str `{old}` did not appear verbatim in {path}."
            )
        if len(starts) > 1:
            lines = [content.count("\n", 0, index) + 1 for index in starts]
            raise _Refused(
                f"No replacement was performed. Multiple occurrences of old_str `{old}` "
                f"in lines: {lines}. Please ensure it is unique"
            )
        self._save(path, content.replace(old, action.new_str or "", 1))
        return "The memory file has been edited."

    def _insert(self, action: MemoryAction, files: dict[str, str]) -> str:
        path = self._file(action.path)
        if path not in files:
            raise _Refused(f"Error: The path {path} does not exist")
        lines = files[path].split("\n")
        line = action.insert_line if action.insert_line is not None else -1
        if not 0 <= line <= len(lines):
            raise _Refused(
                f"Error: Invalid `insert_line` parameter: {line}. It should be within "
                f"the range of lines of the file: [0, {len(lines)}]"
            )
        lines.insert(line, (action.insert_text or "").removesuffix("\n"))
        self._save(path, "\n".join(lines))
        return f"The file {path} has been edited."

    def _delete(self, action: MemoryAction, files: dict[str, str]) -> str:
        path = self._resolve(action.path)
        if path in (ROOT, USER_DIR, REPO_DIR):
            raise _Refused(f"Error: {path} cannot be deleted")
        targets = [path] if path in files else list(_children(path, files))
        if not targets:
            raise _Refused(f"Error: The path {path} does not exist")
        for target in targets:
            self.store.delete(target)
        return f"Successfully deleted {path}"

    def _rename(self, action: MemoryAction, files: dict[str, str]) -> str:
        old, new = self._resolve(action.old_path), self._file(action.new_path)
        if old in (ROOT, USER_DIR, REPO_DIR):
            raise _Refused(f"Error: {old} cannot be renamed")
        sources = [old] if old in files else list(_children(old, files))
        if not sources:
            raise _Refused(f"Error: The path {old} does not exist")
        if new in files or _children(new, files):
            raise _Refused(f"Error: The destination {new} already exists")
        for source in sources:
            self.store.save(new + source[len(old) :], files[source])
            self.store.delete(source)
        return f"Successfully renamed {old} to {new}"

    def _dirs(self) -> list[str]:
        return [ROOT, USER_DIR, REPO_DIR] if self.store.has_repo else [ROOT, USER_DIR]

    def _resolve(self, path: str | None) -> str:
        resolved = posixpath.normpath(path or "")
        if resolved != ROOT and not resolved.startswith(ROOT + "/"):
            raise _Refused(f"Error: {path} is outside {ROOT}")
        if (resolved == REPO_DIR or resolved.startswith(REPO_DIR + "/")) and not self.store.has_repo:
            raise _Refused(f"Error: this conversation has no repository, so {REPO_DIR} is unavailable")
        return resolved

    def _file(self, path: str | None) -> str:
        resolved = self._resolve(path)
        if not resolved.startswith((USER_DIR + "/", REPO_DIR + "/")):
            raise _Refused(f"Error: memory files live under {USER_DIR}/ or {REPO_DIR}/")
        return resolved

    def _save(self, path: str, content: str) -> None:
        if len(content) > MAX_MEMORY_CHARS:
            raise _Refused(
                f"Error: a memory file is limited to {MAX_MEMORY_CHARS} characters. "
                "Keep one topic per file."
            )
        self.store.save(path, content)


def memory_index(files: dict[str, str]) -> str:
    if not files:
        return "No memories saved yet."
    lines = [
        f"{path}: {next((line.strip() for line in content.splitlines() if line.strip()), '')[:150]}"
        for path, content in sorted(files.items())
    ]
    if len(lines) > MAX_INDEX_LINES:
        hidden = len(lines) - MAX_INDEX_LINES
        lines = lines[:MAX_INDEX_LINES] + [f"... {hidden} more; use memory view {ROOT}"]
    return "\n".join(lines)


def _children(path: str, files: dict[str, str]) -> dict[str, str]:
    return {file: content for file, content in files.items() if file.startswith(path + "/")}


def _size(size: int) -> str:
    return f"{size / 1024:.1f}K"
