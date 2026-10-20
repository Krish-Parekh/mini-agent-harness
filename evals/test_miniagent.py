from __future__ import annotations

import pytest
from deepeval import assert_test
from deepeval.dataset import Golden

from evals.dataset import agent_dataset
from evals.metrics import WorkspaceCheck, trace_metrics
from evals.tracing import instrument, run_agent

instrument()


@pytest.mark.parametrize("golden", agent_dataset.goldens, ids=lambda golden: golden.name)
def test_miniagent(golden: Golden):
    outcome = run_agent(golden)
    assert_test(
        golden=golden,
        metrics=[*trace_metrics(golden.input), WorkspaceCheck(outcome.check_passed, outcome.check_detail)],
    )
