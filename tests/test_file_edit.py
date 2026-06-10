from __future__ import annotations

from miniagent.tools.file_edit import FileEditAction, FileEditTool
from miniagent.tools.file_edit_match import (
    apply_str_replace,
    diagnose_no_match,
)

tool = FileEditTool()


def edit(sandbox, **kwargs):
    return tool.execute(FileEditAction(**kwargs), sandbox)


# --- str_replace through the tool ------------------------------------------


def test_str_replace_exact(sandbox):
    sandbox.write_file("a.py", "x = 1\ny = 2\n")
    obs = edit(sandbox, command="str_replace", path="a.py", old_str="x = 1", new_str="x = 99")
    assert not obs.error
    assert sandbox.read_file("a.py") == "x = 99\ny = 2\n"


def test_str_replace_non_unique(sandbox):
    sandbox.write_file("a.py", "v = 1\nv = 1\n")
    obs = edit(sandbox, command="str_replace", path="a.py", old_str="v = 1", new_str="v = 2")
    assert obs.error
    assert "not unique" in obs.output
    assert "2 matches" in obs.output


def test_str_replace_already_applied(sandbox):
    sandbox.write_file("a.py", "value = old\n")
    edit(sandbox, command="str_replace", path="a.py", old_str="value = old", new_str="value = new")
    # Re-issuing the same edit on the now-updated file: stale old_str, new_str present.
    obs = edit(sandbox, command="str_replace", path="a.py", old_str="value = old", new_str="value = new")
    assert obs.error
    assert "already applied" in obs.output.lower()
    assert obs.output.strip().endswith("Re-run `file_edit view` on this path before editing.")


def test_str_replace_stale_after_prior_edit(sandbox):
    sandbox.write_file("a.py", "count = 0\n")
    edit(sandbox, command="str_replace", path="a.py", old_str="count = 0", new_str="count = 1")
    obs = edit(sandbox, command="str_replace", path="a.py", old_str="count = 0", new_str="count = 2")
    assert obs.error
    assert "not found" in obs.output
    assert "current file excerpt" in obs.output


# --- view -------------------------------------------------------------------


def test_view_raw_no_prefixes(sandbox):
    content = "first line\nsecond line\n"
    sandbox.write_file("a.py", content)
    obs = edit(sandbox, command="view", path="a.py")
    assert obs.output == content
    assert "\t" not in obs.output


def test_view_empty(sandbox):
    sandbox.write_file("e.py", "")
    obs = edit(sandbox, command="view", path="e.py")
    assert obs.output == "(empty file)"


def test_view_range_slice(sandbox):
    sandbox.write_file("a.py", "l1\nl2\nl3\nl4\n")
    obs = edit(sandbox, command="view", path="a.py", view_range=[2, 3])
    assert obs.output == "# lines 2-3 of a.py\nl2\nl3"


def test_view_range_to_eof(sandbox):
    sandbox.write_file("a.py", "l1\nl2\nl3\n")
    obs = edit(sandbox, command="view", path="a.py", view_range=[2, -1])
    assert obs.output == "# lines 2-3 of a.py\nl2\nl3"


def test_view_range_out_of_bounds(sandbox):
    sandbox.write_file("a.py", "l1\nl2\n")
    obs = edit(sandbox, command="view", path="a.py", view_range=[5, 9])
    assert obs.error
    assert "out of bounds" in obs.output


# --- diagnostics (pure functions) ------------------------------------------


def test_apply_str_replace_counts():
    assert apply_str_replace("a b c", "b", "B") == ("a B c", 1)
    assert apply_str_replace("a b c", "z", "Z") == ("a b c", 0)
    assert apply_str_replace("a a", "a", "b") == ("a a", 2)


def test_diagnose_crlf():
    content = "a\r\nb\r\nc\r\n"
    msg = diagnose_no_match(content, "a\nb", "X", "f.py")
    assert "CRLF" in msg


def test_diagnose_line_number_paste():
    content = "alpha\nbeta\n"
    old = "     1\talpha\n     2\tbeta"
    msg = diagnose_no_match(content, old, "X", "f.py")
    assert "line-number prefix" in msg


def test_diagnose_trim_near_miss():
    content = "x = foo\n"
    msg = diagnose_no_match(content, "   x = foo   ", "X", "f.py")
    assert "whitespace" in msg


def test_diagnose_always_reread():
    msg = diagnose_no_match("totally different content\n", "no such text", "X", "f.py")
    assert "current file excerpt" in msg
    assert msg.strip().endswith("Re-run `file_edit view` on this path before editing.")
