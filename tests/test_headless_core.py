from __future__ import annotations

import subprocess
import sys

from miniagent import cli
from miniagent.agent import _file_sketch
from miniagent.sandbox.local import LocalSandbox
from tests.replay import cassette  # noqa: F401


def test_the_cli_answers_and_leaves_the_workspace_untouched(
    tmp_path, monkeypatch, capsys, cassette  # noqa: F811
):
    (tmp_path / "notes.txt").write_text("deploy window: friday\n")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "mini-agent",
            "Run `seq 1 20000` in the terminal and tell me the last number it prints.",
            "--workspace",
            str(tmp_path),
            "--model",
            "anthropic/claude-haiku-5-5",
        ],
    )

    code = cli.main()

    assert code == 0
    assert "20000" in capsys.readouterr().out
    assert sorted(p.name for p in tmp_path.iterdir()) == ["notes.txt"]


def test_the_sketch_lists_files_with_or_without_git(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "main.py").write_text("print(1)\n")
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / ".gitignore").write_text("build/\n")
    (repo / "app.py").write_text("x = 1\n")
    (repo / "build").mkdir()
    (repo / "build" / "out.bin").write_text("artifact\n")

    plain_sketch = _file_sketch(LocalSandbox(str(plain)))
    repo_sketch = _file_sketch(LocalSandbox(str(repo)))

    assert "main.py" in plain_sketch
    assert "app.py" in repo_sketch and ".gitignore" in repo_sketch
    assert "out.bin" not in repo_sketch
