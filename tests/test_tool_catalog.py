from __future__ import annotations

from miniagent.tools.catalog import CATALOG_PATH, render_catalog


def test_committed_tool_catalog_matches_the_tool_schemas():
    assert CATALOG_PATH.read_text() == render_catalog(), (
        "Tool schemas changed; regenerate with `uv run python -m miniagent.tools.catalog`."
    )
