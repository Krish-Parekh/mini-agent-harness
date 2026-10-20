from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean

RESULTS = Path(__file__).parent / "results"
METRICS = ("Task Completion", "Step Efficiency", "Tool Correctness", "Expectations", "Workspace Check")


def _latest_run(identifier: str) -> dict:
    for path in sorted(RESULTS.glob("test_run_*.json"), reverse=True):
        run = json.loads(path.read_text())
        if run.get("identifier") == identifier:
            return run
    raise SystemExit(f"no saved test run with identifier {identifier!r}")


def _row(name: str, cases: list[dict]) -> str:
    scores = defaultdict(list)
    for case in cases:
        for metric in case["metricsData"]:
            if metric["score"] is not None:
                scores[metric["name"]].append(metric["score"])
    meta = [case["trace"]["metadata"] for case in cases]
    prompt = sum(m["prompt_tokens"] for m in meta)
    cached = sum(m["cached_prompt_tokens"] for m in meta)
    cells = [f"{name:26}", f"{len(cases):>3}", f"{mean(c['success'] for c in cases):>5.0%}"]
    cells += [f"{mean(scores[m]):>6.2f}" if scores[m] else f"{'-':>6}" for m in METRICS]
    cells += [f"{mean(m['steps'] for m in meta):>6.1f}", f"{prompt / len(meta):>8.0f}"]
    cells += [f"{cached / prompt if prompt else 0:>6.0%}", f"{mean(m['seconds'] for m in meta):>6.1f}"]
    cells += [f"{sum(m['cost_usd'] for m in meta):>7.3f}", f"{sum(1 for m in meta if m['error']):>4}"]
    return " ".join(cells)


def main() -> None:
    header = f"{'golden':26} {'n':>3} {'pass':>5} {'done':>6} {'eff':>6} {'tools':>6} {'expect':>6} {'check':>6} {'steps':>6} {'prompt':>8} {'cache':>6} {'secs':>6} {'cost':>7} {'errs':>4}"
    for identifier in sys.argv[1:]:
        cases = [c for c in _latest_run(identifier)["testCases"] if c.get("trace")]
        by_golden = defaultdict(list)
        for case in cases:
            by_golden[case["trace"]["name"]].append(case)
        print(f"\n== {identifier}\n{header}")
        for name in sorted(by_golden):
            print(_row(name, by_golden[name]))
        print(_row("ALL", cases))


if __name__ == "__main__":
    main()
