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


def test_viewed_file_can_be_edited_repeatedly(tmp_path):
    tool, sandbox = _setup(tmp_path)
    _act(tool, sandbox, "view")
    assert not _act(tool, sandbox, "str_replace", old_str="x = 1", new_str="x = 2").error
    assert not _act(tool, sandbox, "str_replace", old_str="x = 2", new_str="x = 3").error
    assert (tmp_path / "a.py").read_text() == "x = 3\n"


def test_a_file_changed_outside_the_tool_is_stale(tmp_path):
    tool, sandbox = _setup(tmp_path)
    _act(tool, sandbox, "view")
    (tmp_path / "a.py").write_text("x = 99\n")
    result = _act(tool, sandbox, "str_replace", old_str="x = 99", new_str="x = 2")
    assert result.error and "changed since you last viewed it" in result.output


def test_a_partial_view_counts_as_observed(tmp_path):
    tool, sandbox = _setup(tmp_path)
    _act(tool, sandbox, "view", view_range=[1, 1])
    assert not _act(tool, sandbox, "str_replace", old_str="x = 1", new_str="x = 2").error


def test_absolute_and_relative_paths_are_the_same_file(tmp_path):
    tool, sandbox = _setup(tmp_path)
    _act(tool, sandbox, "view", path=str(tmp_path / "a.py"))
    assert not _act(tool, sandbox, "str_replace", old_str="x = 1", new_str="x = 2").error


def test_create_new_file_is_allowed_and_then_editable(tmp_path):
    tool, sandbox = _setup(tmp_path)
    assert not _act(tool, sandbox, "create", path="b.py", content="y = 1\n").error
    assert not _act(tool, sandbox, "str_replace", path="b.py", old_str="y = 1", new_str="y = 2").error


def test_create_over_an_unviewed_file_is_refused(tmp_path):
    tool, sandbox = _setup(tmp_path)
    result = _act(tool, sandbox, "create", content="wiped\n")
    assert result.error and "already exists" in result.output
    assert (tmp_path / "a.py").read_text() == "x = 1\n"


def test_create_over_a_freshly_viewed_file_overwrites(tmp_path):
    tool, sandbox = _setup(tmp_path)
    _act(tool, sandbox, "view")
    result = _act(tool, sandbox, "create", content="new\n")
    assert not result.error and result.output == "Overwrote a.py"
