from __future__ import annotations

import shutil
import subprocess

import pytest

from miniagent.sandbox.local import LocalSandbox
from miniagent.tools.search import MAX_FILES, GlobAction, GlobTool, GrepAction, GrepTool

pytestmark = pytest.mark.skipif(shutil.which("rg") is None, reason="ripgrep not installed")


@pytest.fixture
def sandbox(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text("build/\n")
    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "out.py").write_text("def create_user(): pass\n")
    (tmp_path / "src" / "api").mkdir(parents=True)
    (tmp_path / "src" / "api" / "routes.py").write_text(
        "def create_user():\n    return save_user()\n"
    )
    (tmp_path / "src" / "models.py").write_text("class User:\n    pass\n")
    (tmp_path / "web.ts").write_text("export const createUser = () => 1\n")
    return LocalSandbox(str(tmp_path))


def _grep(sandbox, **kwargs):
    return GrepTool().execute(GrepAction(**kwargs), sandbox, None)


def _glob(sandbox, **kwargs):
    return GlobTool().execute(GlobAction(**kwargs), sandbox, None)


def test_grep_groups_matching_lines_by_file(sandbox):
    result = _grep(sandbox, pattern="save_user")
    assert result.text == "src/api/routes.py\n2:    return save_user()"


def test_grep_filters_by_include_and_skips_gitignored_files(sandbox):
    result = _grep(sandbox, pattern="create", include="*.py")
    assert result.text == "src/api/routes.py\n1:def create_user():"


def test_grep_with_no_matches_says_so(sandbox):
    assert _grep(sandbox, pattern="nothing_matches_this").text == "No matches."


def test_glob_matches_workspace_relative_paths(sandbox):
    assert sorted(_glob(sandbox, pattern="*.py").text.splitlines()) == [
        "src/api/routes.py",
        "src/models.py",
    ]
    assert _glob(sandbox, pattern="src/api/*.py", path="src").text == "src/api/routes.py"


def test_glob_stops_at_the_file_cap(tmp_path):
    for index in range(MAX_FILES + 5):
        (tmp_path / f"f{index}.txt").write_text("")
    lines = _glob(LocalSandbox(str(tmp_path)), pattern="*.txt").text.splitlines()
    assert len(lines) == MAX_FILES + 1
    assert lines[-1].startswith(f"[Output stopped at {MAX_FILES} lines.")


@pytest.mark.parametrize("path", ["..", "/etc"])
def test_paths_outside_the_workspace_are_rejected(sandbox, path):
    result = _grep(sandbox, pattern="x", path=path)
    assert result.to_llm_text() == f"ERROR: {path} is outside the workspace."
