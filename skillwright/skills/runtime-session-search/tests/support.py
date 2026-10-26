from __future__ import annotations

import importlib.machinery
import importlib.util
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "bin" / "runtime-session-search"
FIXTURES = ROOT / "tests" / "fixtures"
LOADER = importlib.machinery.SourceFileLoader("runtime_session_search_cli", str(BIN))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
assert SPEC is not None
search = importlib.util.module_from_spec(SPEC)
sys.modules.setdefault(LOADER.name, search)
if not hasattr(sys.modules[LOADER.name], "find"):
    LOADER.exec_module(sys.modules[LOADER.name])
search = sys.modules[LOADER.name]
stores = search.load_stores()
