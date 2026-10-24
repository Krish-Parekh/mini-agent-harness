from __future__ import annotations

import json
import re
import shlex
import time
from typing import Any

import tree_sitter_bash
from pydantic import Field, model_validator
from tree_sitter import Language, Parser

from miniagent.sandbox.base import KILLED_EXIT_CODE, CommandResult, Sandbox
from miniagent.schema import Action, Observation
from miniagent.tools.base import Tool, ToolContext

TMUX = "tmux -L miniagent"
NO_CHANGE_TIMEOUT_S = 30
HISTORY_LIMIT = 10_000
PS1_BEGIN = "\n###PS1JSON###\n"
PS1_END = "\n###PS1END###"
_PS1_REGEX = re.compile(
    rf"^{PS1_BEGIN.strip()}((?:(?!{PS1_BEGIN.strip()}).)*?){PS1_END.strip()}",
    re.DOTALL | re.MULTILINE,
)
_PS1 = (
    PS1_BEGIN
    + json.dumps({"exit_code": "$?", "working_dir": "$(pwd)"}, indent=2).replace('"', r"\"")
    + PS1_END
    + "\n"
)
_POLL_S = 0.1
_PROMPT_TIMEOUT_S = 30
_WIDTH = 256
_HEIGHT = 200
_TIMEOUT_MESSAGE = (
    "You may wait longer to see additional output by sending empty command '' "
    "with is_input=true, send other input to interact with the current process, "
    'send keys ("C-c", "C-z", "C-d") to interrupt/kill the previous command '
    "before sending your new command, or use the timeout parameter in terminal "
    "for future commands."
)
_CONTINUE_PREFIX = "[Below is the output of the previous command.]\n"
_RESTARTED = (
    "A new terminal session was started: the previous one was reset or ended "
    "(for example by a top-level `exit`). Environment variables, the working "
    "directory and running processes from before are gone."
)
_KEYS = {
    "ENTER": "Enter",
    "TAB": "Tab",
    "BS": "BSpace",
    "ESC": "Escape",
    "UP": "Up",
    "DOWN": "Down",
    "LEFT": "Left",
    "RIGHT": "Right",
    "HOME": "Home",
    "END": "End",
    "PGUP": "PPage",
    "PGDN": "NPage",
}
_CTRL_KEY = re.compile(r"(?:C|CTRL)[-+]([A-Z])")
_BASH = Language(tree_sitter_bash.language())

DESCRIPTION = """Run a bash command in a persistent terminal session in the workspace.

### Command execution
* One command at a time. To run several in sequence, chain them on one line with `&&` or `;`.
* Persistent session: the working directory, environment variables, virtual environments and other shell state persist across calls. The session starts in the workspace root. File tools still resolve relative paths against the workspace root, not the terminal's working directory.
* Soft timeout: without `timeout`, a command that prints no new output for 30 seconds returns exit code `-1` and keeps running.
* `timeout` is a hard limit in seconds; when it passes, the call returns exit code `-1` and the command keeps running. Raise it for installs, builds and test suites (120-600), or for commands with a known duration such as `sleep`.
* Do not use `set -e`, `set -eu`, `set -euo pipefail` or a top-level `exit`: they end the persistent shell.

### Long-running and interactive commands
* Run servers, watchers and other commands that never end in the background with output to a log file, e.g. `python3 app.py > server.log 2>&1 &`, then read the log.
* Interactive programs work: start a REPL such as `python3` or a command that reads input, then send its input with `is_input=true`.
* Exit code `-1` means the command is still running. With `is_input=true` you can:
  - send an empty `command` to get new output
  - send text to its stdin (Enter is pressed after the text)
  - send `C-c` to interrupt it, `C-d` for end of input, `C-z` to suspend it, or any `C-<letter>`
  - send `UP`, `DOWN`, `LEFT`, `RIGHT`, `HOME`, `END`, `PGUP`, `PGDN`, `TAB`, `ESC`, `BS` or `ENTER`
* A new command is refused while the previous one is still running. Stop it with `C-c` first.

### Usage
* Use it for git work (`git log --oneline -10`, `git diff`), skimming a slice (`sed -n '40,90p' file.py`), verification (`python -m pytest tests/test_x.py -x -q`) and multi-file work.
* Search with the `grep` and `glob` tools instead of `rg`, `grep` or `find`.
* Keep output small: prefer `| head -50` and narrow test invocations over full suites. Large output is truncated.
* Set `description` to a short summary of the command.
* Before `rm` or `mv`, check the resolved target path, and guard variables with `${VAR:?}` so an empty value cannot widen the target. If the sandbox denies a command, do not retry the same effect another way.

### Reset
* Set `reset=true` to start a fresh terminal when the current one is unresponsive. This clears environment variables, the working directory and running processes."""


def _split_bash_commands(commands: str) -> list[str]:
    if not commands.strip():
        return [""]
    source = commands.encode()
    root = Parser(_BASH).parse(source).root_node
    if root.has_error:
        return [commands]
    statements = [c for c in root.named_children if c.type != "comment"]
    if not statements:
        return [commands]
    boundaries = [statements[0].start_byte]
    for current, following in zip(statements, statements[1:]):
        if b"\n" in source[current.end_byte : following.start_byte]:
            boundaries.append(following.start_byte)
    boundaries.append(len(source))
    return [source[a:b].decode().rstrip() for a, b in zip(boundaries, boundaries[1:])]


def shell_command(arguments: dict[str, Any]) -> str | None:
    if arguments.get("is_input"):
        return None
    return str(arguments.get("command", "")).strip() or None


def _key_name(text: str) -> str | None:
    upper = text.strip().upper()
    if upper in _KEYS:
        return _KEYS[upper]
    match = _CTRL_KEY.fullmatch(upper)
    return f"C-{match.group(1).lower()}" if match else None


def _ps1_matches(screen: str) -> list[re.Match[str]]:
    matches = []
    for match in _PS1_REGEX.finditer(screen):
        try:
            json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            continue
        matches.append(match)
    return matches


def _checked(result: CommandResult) -> CommandResult:
    if result.exit_code != 0:
        raise RuntimeError(
            f"tmux failed with exit code {result.exit_code}: "
            f"{(result.stderr or result.stdout).strip()}"
        )
    return result


def _screen(result: CommandResult) -> str:
    return "\n".join(line.rstrip() for line in result.stdout.split("\n"))


def _at_prompt(screen: str) -> bool:
    return screen.rstrip().endswith(PS1_END.rstrip())


def _between_prompts(
    screen: str, matches: list[re.Match[str]], before_last: bool = False
) -> str:
    if len(matches) == 1:
        if before_last:
            return screen[: matches[0].start()]
        return screen[matches[0].end() + 1 :]
    if not matches:
        return screen
    combined = ""
    for current, following in zip(matches, matches[1:]):
        combined += screen[current.end() + 1 : following.start()] + "\n"
    return combined + screen[matches[-1].end() + 1 :]


class TerminalAction(Action):
    command: str = Field(
        description=(
            "The bash command to run. Can be empty with `is_input=true` to read new "
            "output of a command that returned exit code `-1`. With `is_input=true` "
            "it can also be text for the running process or a key: `C-c` (Ctrl+C), "
            "`C-d` (Ctrl+D, end of input), `C-z` (Ctrl+Z), any `C-<letter>`, "
            "`UP`, `DOWN`, `LEFT`, `RIGHT`, `HOME`, `END`, `PGUP`, `PGDN`, `TAB`, "
            "`ESC`, `BS` (Backspace) or `ENTER`. Only one command at a time."
        )
    )
    is_input: bool = Field(
        False,
        description=(
            "If true, `command` is input to the running process instead of a new "
            "command."
        ),
    )
    timeout: float | None = Field(
        None,
        ge=0,
        description=(
            "Hard time limit in seconds. When it passes the call returns and the "
            "command keeps running. Without it, the call returns after "
            f"{NO_CHANGE_TIMEOUT_S} seconds with no new output. Set a higher value "
            "for commands that take long, such as installs and test suites, or "
            "that have a known duration, such as `sleep`."
        ),
    )
    reset: bool = Field(
        False,
        description=(
            "If true, start a fresh terminal session first. Use it only when the "
            "terminal is unresponsive: environment variables, the working "
            "directory and running processes are lost. Cannot be combined with "
            "`is_input`."
        ),
    )
    description: str = Field(
        "", description="5-10 word summary of what the command does, shown to the user."
    )

    @model_validator(mode="after")
    def _reset_starts_a_command(self) -> TerminalAction:
        if self.reset and self.is_input:
            raise ValueError("reset cannot be combined with is_input")
        return self


class TerminalObservation(Observation):
    command: str
    output: str
    exit_code: int = -1
    working_dir: str | None = None
    prefix: str = ""
    suffix: str = ""
    error: bool = False
    duration_ms: int = 0

    def to_llm_text(self) -> str:
        text = f"{self.prefix}{self.output}{self.suffix}"
        if self.working_dir:
            text += f"\n[Current working directory: {self.working_dir}]"
        return f"ERROR: {text}" if self.error else text

    def ui_details(self) -> dict[str, Any]:
        return {
            "output": self.output,
            "exit_code": self.exit_code,
            "working_dir": self.working_dir,
        }


class TerminalSession:
    def __init__(
        self, sandbox: Sandbox, name: str, no_change_timeout_s: int = NO_CHANGE_TIMEOUT_S
    ) -> None:
        self.sandbox = sandbox
        self.name = name
        self.no_change_timeout_s = no_change_timeout_s
        self.started = False
        self.running = False
        self.prev_output = ""
        self.cwd = sandbox.workspace_dir
        self._session_target = shlex.quote(f"={name}")
        self._pane_target = shlex.quote(f"={name}:")
        self._buffer = shlex.quote(name)
        self._capture = f"{TMUX} capture-pane -J -p -S - -t {self._pane_target}"

    def execute(self, action: TerminalAction) -> TerminalObservation:
        notice = self._ensure_started(action.reset)
        command = action.command.strip()
        if action.reset and not command:
            return TerminalObservation(
                command="", output=notice, exit_code=0, working_dir=self.cwd
            )
        observation = self._execute(command, action.is_input, action.timeout)
        if notice:
            observation = observation.model_copy(
                update={"prefix": f"{notice}\n\n{observation.prefix}"}
            )
        return observation

    def close(self) -> None:
        if self.started:
            self._run(f"{TMUX} kill-session -t {self._session_target}")
            self.started = False

    def _ensure_started(self, reset: bool) -> str:
        if self.started and not reset and self._alive():
            return ""
        notice = _RESTARTED if self.started or reset else ""
        self._start()
        return notice

    def _alive(self) -> bool:
        return self._run(f"{TMUX} has-session -t {self._session_target}").exit_code == 0

    def _start(self) -> None:
        self._check(
            f"{TMUX} kill-session -t {self._session_target} 2>/dev/null; "
            f"{TMUX} -f /dev/null start-server \\; "
            f"set-option -g history-limit {HISTORY_LIMIT} \\; "
            f"new-session -d -s {self._buffer} -x {_WIDTH} -y {_HEIGHT} "
            f"-c {shlex.quote(self.sandbox.workspace_dir)} bash --noprofile --norc"
        )
        self._send(f"set +H; export PROMPT_COMMAND='export PS1=\"{_PS1}\"'; export PS2=\"\"")
        self._await_prompt()
        self._clear()
        self.started = True
        self.running = False
        self.prev_output = ""
        self.cwd = self.sandbox.workspace_dir

    def _execute(
        self, command: str, is_input: bool, timeout: float | None
    ) -> TerminalObservation:
        if not self.running:
            if not command:
                return self._error(command, "No previous running command to retrieve logs from.")
            if is_input:
                return self._error(command, "No previous running command to interact with.")
        if not is_input:
            commands = _split_bash_commands(command)
            if len(commands) > 1:
                listed = "\n".join(f"({i}) {c}" for i, c in enumerate(commands, 1))
                return self._error(
                    command,
                    "Cannot execute multiple commands at once.\nPlease run each "
                    "command separately OR chain them into a single command via "
                    f"&& or ;\nProvided commands:\n{listed}",
                )

        initial = self._read_screen()
        initial_matches = _ps1_matches(initial)
        if self.running and not is_input and command and not _at_prompt(initial):
            prefix, output = self._output(
                command, _between_prompts(initial, initial_matches), _CONTINUE_PREFIX
            )
            return TerminalObservation(
                command=command,
                output=output,
                prefix=prefix,
                suffix=(
                    f'\n[Your command "{command}" is NOT executed. The previous '
                    "command is still running - You CANNOT send new commands until "
                    "the previous command is completed. By setting `is_input` to "
                    f"`true`, you can interact with the current process: {_TIMEOUT_MESSAGE}]"
                ),
                error=True,
            )

        if command:
            self._send(command)
        started = last_change = time.monotonic()
        last = initial
        stopped = False
        while True:
            screen = self._poll()
            if screen is None:
                self._send("C-c")
                stopped = True
                continue
            matches = _ps1_matches(screen)
            now = time.monotonic()
            if screen != last:
                last = screen
                last_change = now
            if (not command or screen != initial) and (
                len(matches) > len(initial_matches) or _at_prompt(screen)
            ):
                return self._completed(command, screen, matches, stopped)
            if timeout is None and now - last_change >= self.no_change_timeout_s:
                return self._still_running(
                    command,
                    screen,
                    matches,
                    f"\n[The command has no new output after {self.no_change_timeout_s} "
                    f"seconds. {_TIMEOUT_MESSAGE}]",
                )
            if timeout is not None and now - started >= timeout:
                return self._still_running(
                    command,
                    screen,
                    matches,
                    f"\n[The command timed out after {timeout:g} seconds. {_TIMEOUT_MESSAGE}]",
                )

    def _completed(
        self, command: str, screen: str, matches: list[re.Match[str]], stopped: bool
    ) -> TerminalObservation:
        if not matches:
            exit_code = -1
            prefix, output = self._output(command, screen)
            suffix = (
                "\n[The command completed but the exit code could not be determined. "
                "Terminal output may have corrupted the PS1 metadata markers.]"
            )
        else:
            metadata = json.loads(matches[-1].group(1))
            exit_code = int(metadata["exit_code"])
            self.cwd = metadata["working_dir"] or self.cwd
            scrolled_off = len(matches) == 1
            raw = _between_prompts(screen, matches, before_last=scrolled_off)
            prefix, output = self._output(command, raw)
            if scrolled_off:
                prefix = (
                    "[Previous command outputs are truncated. Showing the last "
                    f"{len(raw.splitlines())} lines of the output below.]\n"
                )
            suffix = f"\n[The command completed with exit code {exit_code}."
            if stopped:
                suffix += " The user stopped the run, so C-c was sent."
            elif key := _key_name(command):
                suffix += f" {key} was sent."
            suffix += "]"
        self.running = False
        self.prev_output = ""
        self._clear()
        return TerminalObservation(
            command=command,
            output=output,
            exit_code=exit_code,
            working_dir=self.cwd,
            prefix=prefix,
            suffix=suffix,
        )

    def _still_running(
        self, command: str, screen: str, matches: list[re.Match[str]], suffix: str
    ) -> TerminalObservation:
        self.running = True
        prefix, output = self._output(
            command, _between_prompts(screen, matches), _CONTINUE_PREFIX
        )
        return TerminalObservation(
            command=command, output=output, prefix=prefix, suffix=suffix
        )

    def _error(self, command: str, message: str) -> TerminalObservation:
        return TerminalObservation(command=command, output=message, error=True)

    def _output(
        self, command: str, raw: str, continue_prefix: str = ""
    ) -> tuple[str, str]:
        prefix = ""
        output = raw
        if self.prev_output:
            output = raw.removeprefix(self.prev_output)
            prefix = continue_prefix
        self.prev_output = raw
        output = output.lstrip().removeprefix(command.lstrip()).lstrip()
        return prefix, output.rstrip()

    def _send(self, text: str) -> None:
        key = _key_name(text)
        if key:
            self._check(f"{TMUX} send-keys -t {self._pane_target} {key}")
            return
        self._check(
            f"printf %s {shlex.quote(text)} | {TMUX} load-buffer -b {self._buffer} - && "
            f"{TMUX} paste-buffer -d -b {self._buffer} -t {self._pane_target} && "
            f"{TMUX} send-keys -t {self._pane_target} Enter"
        )

    def _poll(self) -> str | None:
        result = self._run(f"sleep {_POLL_S} && {self._capture}")
        if result.exit_code == KILLED_EXIT_CODE:
            return None
        return _screen(_checked(result))

    def _await_prompt(self) -> None:
        deadline = time.monotonic() + _PROMPT_TIMEOUT_S
        screen = self._read_screen()
        while not _at_prompt(screen):
            if time.monotonic() > deadline:
                raise RuntimeError(f"terminal prompt did not appear: {screen[-500:]!r}")
            screen = _screen(self._check(f"sleep {_POLL_S} && {self._capture}"))

    def _clear(self) -> None:
        self._check(
            f"{TMUX} send-keys -R -t {self._pane_target} \\; clear-history -t {self._pane_target} "
            f"\\; send-keys -t {self._pane_target} Enter"
        )
        self._await_prompt()

    def _read_screen(self) -> str:
        return _screen(self._check(self._capture))

    def _run(self, script: str) -> CommandResult:
        return self.sandbox.run_command(script, timeout=10)

    def _check(self, script: str) -> CommandResult:
        return _checked(self._run(script))


class TerminalTool(Tool):
    name = "terminal"
    description = DESCRIPTION
    action_type = TerminalAction
    observation_type = TerminalObservation

    def __init__(self, no_change_timeout_s: int = NO_CHANGE_TIMEOUT_S) -> None:
        self.no_change_timeout_s = no_change_timeout_s
        self._session: TerminalSession | None = None

    def execute(
        self, action: TerminalAction, sandbox: Sandbox, context: ToolContext
    ) -> TerminalObservation:
        if self._session is None:
            self._session = TerminalSession(
                sandbox, f"miniagent-{context.conversation.id}", self.no_change_timeout_s
            )
        started = time.perf_counter()
        observation = self._session.execute(action)
        return observation.model_copy(
            update={"duration_ms": round((time.perf_counter() - started) * 1000)}
        )

    def close(self) -> None:
        if self._session is not None:
            self._session.close()
