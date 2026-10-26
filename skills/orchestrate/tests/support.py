from __future__ import annotations

import importlib.machinery
import importlib.util
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "bin" / "orchestrate"
LOADER = importlib.machinery.SourceFileLoader("orchestrate_cli", str(BIN))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
assert SPEC is not None
orchestrate = importlib.util.module_from_spec(SPEC)
sys.modules.setdefault(LOADER.name, orchestrate)
if not hasattr(sys.modules[LOADER.name], "resolve"):
    LOADER.exec_module(sys.modules[LOADER.name])
orchestrate = sys.modules[LOADER.name]

def load_herdr():
    herdr_bin = ROOT.parent / "herdr" / "bin" / "herdr"
    if not herdr_bin.is_file():
        herdr_bin = Path.home() / ".foxrun/skills/herdr/bin/herdr"
    loader = importlib.machinery.SourceFileLoader("herdr_cli_for_orchestrate", str(herdr_bin))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = sys.modules.get(loader.name)
    if module is None:
        module = importlib.util.module_from_spec(spec)
        sys.modules[loader.name] = module
        loader.exec_module(module)
    return module
