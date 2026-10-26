#!/usr/bin/env python3
"""Filesystem roots for installed agents. Standard library only."""
from __future__ import annotations
import os
import shutil
from pathlib import Path

def _path(name: str, default: Path) -> Path:
    return Path(os.environ.get(name,str(default))).expanduser()

def roots() -> dict[str, Path]:
    home=Path.home()
    system=_path('FOXRUN_HOME',home/'.foxrun')
    portfolio=_path('FOXRUN_PORTFOLIO',home/'foxrun')
    state=_path('FOXRUN_STATE',home/'.local/state/foxrun')
    return {'system':system,'portfolio':portfolio,'state':state,
            'repo':system/'agents','vault':portfolio,'hermes':state/'hermes',
            'shelf':system/'skills','modules':system/'modules'}

def hermes_available() -> bool:
    return False  # Claude and Codex on day one.

def tool_path(repo: Path, name: str) -> Path:
    """Find an installed tool, or a legacy repository test fixture."""
    installed = repo / 'tools' / name
    return installed if installed.is_file() else repo / name
