from __future__ import annotations

import pytest

from miniagent.sandbox.local import LocalSandbox
from miniagent.tools.bash import BashAction, BashTool


def test_workdir_runs_the_command_in_that_directory(tmp_path):
    (tmp_path / "pkg").mkdir()
    result = BashTool().execute(
        BashAction(command="pwd", workdir="pkg", description="Print dir"),
        LocalSandbox(str(tmp_path)),
    )
    assert result.exit_code == 0
    assert result.stdout.strip().endswith("/pkg")


@pytest.mark.parametrize("workdir", ["..", "../other", "/etc"])
def test_workdir_outside_the_workspace_is_rejected(tmp_path, workdir):
    result = BashTool().execute(
        BashAction(command="pwd", workdir=workdir), LocalSandbox(str(tmp_path))
    )
    assert result.exit_code == 2
    assert "outside the workspace" in result.stderr
