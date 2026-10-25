from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from harbor.environments.docker.docker import DockerEnvironment
from harbor.models.environment_type import EnvironmentType
from harbor.models.task.config import EnvironmentConfig as TaskEnvironmentConfig
from harbor.models.trajectories import Trajectory
from harbor.models.trial.config import (
    AgentConfig,
    EnvironmentConfig,
    TaskConfig,
    TrialConfig,
)
from harbor.models.trial.paths import TrialPaths
from harbor.trial.trial import Trial

from miniagent.harbor.sandbox import HarborSandbox
from miniagent.prompts import FINISH_CHECKLIST_PROMPT
from miniagent.sandbox.base import TIMEOUT_EXIT_CODE
from tests.replay import cassette  # noqa: F401

TASK = Path(__file__).parent / "fixtures" / "harbor_task"


def _docker_running() -> bool:
    try:
        DockerEnvironment.preflight()
    except SystemExit:
        return False
    return True


pytestmark = pytest.mark.skipif(not _docker_running(), reason="docker is not running")


@pytest.fixture
async def environment(tmp_path):
    trial_paths = TrialPaths(trial_dir=tmp_path / "trial")
    trial_paths.mkdir()
    environment = DockerEnvironment(
        environment_dir=TASK / "environment",
        environment_name="harbor-sandbox",
        session_id=f"miniagent-sandbox__{tmp_path.name}",
        trial_paths=trial_paths,
        task_env_config=TaskEnvironmentConfig(),
    )
    await environment.start(force_build=False)
    yield environment
    await environment.stop(delete=True)


async def test_the_sandbox_runs_commands_and_moves_files_through_the_environment(environment):
    sandbox = await HarborSandbox.connect(environment)

    echoed = await asyncio.to_thread(sandbox.run_command, "echo $((6 * 7))")
    timed_out = await asyncio.to_thread(sandbox.run_command, "sleep 5", 1)
    await asyncio.to_thread(sandbox.write_file, "out/notes.txt", "line one\nline two\n")
    content = await asyncio.to_thread(sandbox.read_file, "/app/out/notes.txt")
    listing = await asyncio.to_thread(sandbox.list_files, "out")

    assert sandbox.workspace_dir == "/app"
    assert (echoed.stdout, echoed.exit_code) == ("42\n", 0)
    assert timed_out.exit_code == TIMEOUT_EXIT_CODE
    assert content == "line one\nline two\n"
    assert listing == ["notes.txt"]


async def test_harbor_runs_miniagent_on_a_task_and_grades_it(tmp_path, cassette):  # noqa: F811
    config = TrialConfig(
        task=TaskConfig(path=TASK),
        agent=AgentConfig(
            import_path="miniagent.harbor:MiniAgent",
            model_name="anthropic/claude-haiku-5-5",
            kwargs={"timeout_sec": 600},
        ),
        environment=EnvironmentConfig(type=EnvironmentType.DOCKER, delete=True),
        trials_dir=tmp_path / "trials",
    )

    trial = await Trial.create(config=config)
    result = await trial.run()

    assert result.exception_info is None, result.exception_info
    assert result.verifier_result.rewards == {"reward": 1}
    assert result.agent_result.n_input_tokens > 0
    trajectory = Trajectory.model_validate_json(
        (trial.paths.agent_dir / "trajectory.json").read_text()
    )
    finishes = [
        step.observation.results[0].content
        for step in trajectory.steps
        if step.tool_calls and step.tool_calls[0].function_name == "finish"
    ]
    assert finishes[-2] == FINISH_CHECKLIST_PROMPT
