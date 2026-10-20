from __future__ import annotations

from miniagent.sandbox.local import LocalSandbox
from miniagent.tools.file_edit import FileEditAction, FileEditTool


def _act(tool, sandbox, command, path="a.py", **kwargs):
    return tool.execute(FileEditAction(command=command, path=path, **kwargs), sandbox)


def _setup(tmp_path):
    sandbox = LocalSandbox(str(tmp_path))
    (tmp_path / "a.py").write_text("x = 1\n")
    return FileEditTool(), sandbox


def test_editing_an_unviewed_file_is_refused(tmp_path):
    tool, sandbox = _setup(tmp_path)
    result = _act(tool, sandbox, "str_replace", old_str="x = 1", new_str="x = 2")
    assert result.error
    assert "view a.py first" in result.output
    assert (tmp_path / "a.py").read_text() == "x = 1\n"


def test_a_file_changed_outside_the_tool_is_stale(tmp_path):
    tool, sandbox = _setup(tmp_path)
    _act(tool, sandbox, "view")
    (tmp_path / "a.py").write_text("x = 99\n")
    result = _act(tool, sandbox, "str_replace", old_str="x = 99", new_str="x = 2")
    assert result.error and "changed since you last viewed it" in result.output


def test_create_new_file_is_allowed_and_then_editable(tmp_path):
    tool, sandbox = _setup(tmp_path)
    assert not _act(tool, sandbox, "create", path="b.py", content="y = 1\n").error
    assert not _act(tool, sandbox, "str_replace", path="b.py", old_str="y = 1", new_str="y = 2").error


def test_create_over_an_unviewed_file_is_refused(tmp_path):
    tool, sandbox = _setup(tmp_path)
    result = _act(tool, sandbox, "create", content="wiped\n")
    assert result.error and "already exists" in result.output
    assert (tmp_path / "a.py").read_text() == "x = 1\n"
