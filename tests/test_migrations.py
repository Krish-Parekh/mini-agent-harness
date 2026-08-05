from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

ROOT = Path(__file__).resolve().parent.parent


def _scripts() -> ScriptDirectory:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    return ScriptDirectory.from_config(config)


def test_history_is_linear_and_complete():
    scripts = _scripts()
    revisions = list(scripts.walk_revisions())
    assert revisions, "no migrations found"
    assert len([r for r in revisions if r.down_revision is None]) == 1
    assert len(scripts.get_heads()) == 1


def test_every_revision_can_be_downgraded():
    for revision in _scripts().walk_revisions():
        module = revision.module
        assert hasattr(module, "downgrade")
        source = Path(revision.path).read_text()
        assert "def downgrade()" in source
        body = source.split("def downgrade()", 1)[1]
        assert "op." in body, f"{revision.revision} has an empty downgrade"
