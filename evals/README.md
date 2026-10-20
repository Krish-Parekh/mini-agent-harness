# Evals

DeepEval suite for MiniAgent. Goldens are the `Golden` objects in `AGENT_GOLDENS` (`dataset.py`).

The agent is traced at eval time (`tracing.py` wraps LLM calls and tool calls with `@observe`), so `miniagent/` does not depend on DeepEval. Each agent run is scored on its trace by Task Completion and Step Efficiency, by the golden's `expectations`, and by a deterministic Workspace Check (the edit's check script in `checks/`, or "no files changed" for questions and reviews).

```bash
alias de='uv run --group evals --env-file .env --env-file evals/eval.env deepeval'

de test run evals/test_miniagent.py -n 4 -r 3 -id baseline

uv run --group evals python -m evals.compare baseline
de inspect evals/results
```

One golden: `de test run "evals/test_miniagent.py::test_miniagent[q-sage-overview]"`.

Runs are saved to `evals/results/` (gitignored). Agent tasks run on the host with `LocalSandbox`, in throwaway worktrees of the cached clones under `data/repos/`.
