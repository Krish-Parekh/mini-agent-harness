from __future__ import annotations

from miniagent.agent import _file_sketch, _instructions_block


# --- repository instructions ---------------------------------------------------


def test_no_instruction_file(sandbox):
    assert _instructions_block(sandbox) == ""


def test_agents_md_injected(sandbox):
    sandbox.write_file("AGENTS.md", "Run tests with `uv run pytest`.")
    block = _instructions_block(sandbox)
    assert block.startswith("\n\n## Repository instructions (AGENTS.md)")
    assert "uv run pytest" in block


def test_claude_md_fallback_and_agents_md_priority(sandbox):
    sandbox.write_file("CLAUDE.md", "claude notes")
    assert "(CLAUDE.md)" in _instructions_block(sandbox)

    sandbox.write_file("AGENTS.md", "agents notes")
    block = _instructions_block(sandbox)
    assert "(AGENTS.md)" in block
    assert "claude notes" not in block


def test_empty_instruction_file_skipped(sandbox):
    sandbox.write_file("AGENTS.md", "   \n")
    assert _instructions_block(sandbox) == ""


def test_long_instructions_clipped(sandbox):
    sandbox.write_file("AGENTS.md", "x" * 50_000)
    block = _instructions_block(sandbox)
    assert len(block) < 6_000
    assert "truncated" in block


# --- file sketch ------------------------------------------------------------------


def test_file_sketch_outside_git_repo(sandbox):
    assert _file_sketch(sandbox) == ""


def test_file_sketch_lists_tracked_files(sandbox):
    sandbox.write_file("a.py", "x = 1")
    sandbox.write_file("src/b.py", "y = 2")
    sandbox.run_command("git init -q && git add -A")
    block = _file_sketch(sandbox)
    assert block.startswith("\n\n## Tracked files (git ls-files)")
    assert "a.py" in block
    assert "src/b.py" in block
