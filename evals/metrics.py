from __future__ import annotations

from deepeval.metrics import BaseMetric, StepEfficiencyMetric, TaskCompletionMetric, ToolCorrectnessMetric
from deepeval.test_case import LLMTestCase

from evals import SETTINGS
from evals.judge import LLMJudge

JUDGE = LLMJudge(SETTINGS.policy_model)


def trace_metrics(task: str) -> list[BaseMetric]:
    return [
        TaskCompletionMetric(task=task, model=JUDGE),
        StepEfficiencyMetric(model=JUDGE),
        ToolCorrectnessMetric(threshold=1, model=JUDGE),
    ]


class WorkspaceCheck(BaseMetric):
    def __init__(self, passed: bool, detail: str) -> None:
        self.threshold = 1
        self.passed = passed
        self.detail = detail

    def measure(self, test_case: LLMTestCase, *args, **kwargs) -> float:
        self.score = 1.0 if self.passed else 0.0
        self.reason = self.detail
        self.success = self.passed
        return self.score

    async def a_measure(self, test_case: LLMTestCase, *args, **kwargs) -> float:
        return self.measure(test_case)

    def is_successful(self) -> bool:
        return self.passed

    @property
    def __name__(self) -> str:
        return "Workspace Check"
