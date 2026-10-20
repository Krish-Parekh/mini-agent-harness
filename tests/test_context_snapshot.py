from __future__ import annotations

from tests.context_snapshot import SNAPSHOT_PATH, render


def test_assembled_context_matches_the_committed_snapshot():
    assert SNAPSHOT_PATH.read_text() == render(), (
        "The context sent to the model changed; review the diff and regenerate with "
        "`uv run python -m tests.context_snapshot`."
    )
