from __future__ import annotations

import pytest

from miniagent.sandbox.local import LocalSandbox


@pytest.fixture
def sandbox(tmp_path):
    return LocalSandbox(str(tmp_path))
