from __future__ import annotations

import os
import threading
import uuid

import pytest

from miniagent.sandbox.base import Sandbox
from miniagent.sandbox.local import LocalSandbox
from miniagent.tools.terminal import TMUX, TerminalAction, TerminalObservation, TerminalSession
from tests.test_sandbox_contract import _docker_available


@pytest.fixture(params=["local", "docker"])
def sandbox(request, tmp_path) -> Sandbox:
    if request.param == "local":
        return LocalSandbox(str(tmp_path))
    if not _docker_available():
        pytest.skip("docker image not available")
    from miniagent.sandbox.docker import DockerSandbox

    box = DockerSandbox(
        workspace_dir=str(tmp_path),
        image=os.environ.get("MINIAGENT_DOCKER_IMAGE", "miniagent-sandbox:latest"),
        mounts={str(tmp_path): "rw"},
    )
    request.addfinalizer(box.close)
    return box


@pytest.fixture
def session(sandbox):
    terminal = TerminalSession(
        sandbox, f"miniagent-test-{uuid.uuid4().hex[:8]}", no_change_timeout_s=2
    )
    yield terminal
    terminal.close()


def run(session: TerminalSession, command: str, **kwargs) -> TerminalObservation:
    return session.execute(TerminalAction(command=command, **kwargs))


def test_cd_and_export_persist_across_commands(session):
    session.sandbox.run_command("mkdir sub")
    assert run(session, "cd sub && export GREETING=hello").exit_code == 0
    observation = run(session, 'echo "$GREETING from $(basename "$PWD")"')
    assert observation.output == "hello from sub"
    assert observation.working_dir == f"{session.sandbox.workspace_dir}/sub"


def test_an_activated_venv_stays_active(session):
    assert run(session, "python3 -m venv .venv", timeout=120).exit_code == 0
    assert run(session, "source .venv/bin/activate").exit_code == 0
    observation = run(session, "command -v python")
    assert observation.output == f"{session.sandbox.workspace_dir}/.venv/bin/python"


def test_a_silent_command_keeps_running_until_c_c(session):
    observation = run(session, "sleep 60")
    assert observation.exit_code == -1
    assert "no new output after 2 seconds" in observation.suffix

    refused = run(session, "echo hi")
    assert refused.error
    assert 'Your command "echo hi" is NOT executed' in refused.suffix

    interrupted = run(session, "C-c", is_input=True)
    assert interrupted.exit_code == 130
    assert run(session, "echo after").output == "after"


def test_a_python_repl_reads_input(session):
    started = run(session, "python3")
    assert started.exit_code == -1
    assert ">>>" in started.output

    answered = run(session, "print(6 * 7)", is_input=True)
    assert answered.exit_code == -1
    assert "42" in answered.output

    assert run(session, "C-d", is_input=True).exit_code == 0


def test_read_takes_stdin(session):
    prompted = run(session, 'read -p "Name: " name && echo "Hello $name"')
    assert prompted.exit_code == -1
    assert "Name:" in prompted.output

    answered = run(session, "Ada", is_input=True)
    assert answered.exit_code == 0
    assert "Hello Ada" in answered.output


def test_a_background_server_answers_curl(session):
    started = run(session, "python3 -u -m http.server 0 --bind 127.0.0.1 > server.log 2>&1 &")
    assert started.exit_code == 0
    assert run(session, "until grep -q Serving server.log; do sleep 0.1; done", timeout=30).exit_code == 0
    port = "$(grep -o 'port [0-9]*' server.log | cut -d' ' -f2)"
    observation = run(session, f"curl -s http://127.0.0.1:{port}/")
    assert observation.exit_code == 0
    assert "Directory listing" in observation.output


def test_a_heredoc_runs_without_continuation_prompts(session):
    observation = run(session, "cat <<'EOF' > notes.txt\nfirst \\; line\nsecond\nEOF")
    assert observation.exit_code == 0
    assert ">" not in observation.output
    assert session.sandbox.read_file("notes.txt") == "first \\; line\nsecond\n"


def test_separate_commands_on_separate_lines_are_refused(session):
    observation = run(session, "echo one\necho two")
    assert observation.error
    assert "Cannot execute multiple commands at once" in observation.output


def test_a_failing_command_reports_its_exit_code(session):
    observation = run(session, "cat missing.txt")
    assert observation.exit_code == 1
    assert "No such file or directory" in observation.output


def test_reset_clears_the_environment(session):
    run(session, "export TOKEN=abc")
    observation = run(session, 'echo "token=$TOKEN"', reset=True)
    assert observation.output == "token="
    assert "new terminal session was started" in observation.prefix


def test_an_exited_shell_is_replaced_on_the_next_command(session):
    with pytest.raises(RuntimeError):
        run(session, "exit")
    observation = run(session, "echo back")
    assert observation.output == "back"
    assert "new terminal session was started" in observation.prefix


def test_kill_running_interrupts_the_running_command(session):
    run(session, "true")
    threading.Timer(1, session.sandbox.kill_running).start()
    observation = run(session, "sleep 30", timeout=20)
    assert observation.exit_code == 130
    assert "The user stopped the run" in observation.suffix


def test_close_kills_the_tmux_session(session):
    run(session, "true")
    session.close()
    alive = session.sandbox.run_command(f"{TMUX} has-session -t ={session.name}")
    assert alive.exit_code != 0


def test_reset_ends_what_the_shell_started_but_keeps_detached_services(session):
    stubborn, background, detached = (f"m{uuid.uuid4().hex[:8]}" for _ in range(3))
    detach = (
        "import os; os.fork() and os._exit(0); os.setsid(); "
        f"os.execvp('sh', ['sh', '-c', 'sleep 300; : {detached}'])"
    )
    run(session, f'python3 -c "{detach}" >/dev/null 2>&1 &')
    run(session, f"nohup sh -c 'sleep 300; : {background}' >/dev/null 2>&1 &")
    still_running = run(session, f"sh -c 'trap \"\" HUP INT; sleep 300; : {stubborn}'")
    assert still_running.exit_code == -1
    run(session, "C-c", is_input=True)

    run(session, "echo fresh", reset=True)

    try:
        assert not alive(session, stubborn)
        assert not alive(session, background)
        assert alive(session, detached)
    finally:
        session.sandbox.run_command(f"pkill -f {_pattern(detached)}")


def test_close_ends_what_the_shell_started(session):
    marker = f"m{uuid.uuid4().hex[:8]}"
    run(session, f"nohup sh -c 'sleep 300; : {marker}' >/dev/null 2>&1 &")
    session.close()
    assert not alive(session, marker)


def _pattern(marker: str) -> str:
    return f"'[{marker[0]}]{marker[1:]}'"


def alive(session: TerminalSession, marker: str) -> bool:
    return session.sandbox.run_command(f"pgrep -f {_pattern(marker)}").exit_code == 0
