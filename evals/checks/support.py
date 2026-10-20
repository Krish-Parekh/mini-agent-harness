from __future__ import annotations

import importlib.util
import sys
from types import ModuleType
from unittest.mock import MagicMock


def stub(*names: str) -> None:
    for name in names:
        sys.modules[name] = MagicMock()


def load(name: str, path: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module
