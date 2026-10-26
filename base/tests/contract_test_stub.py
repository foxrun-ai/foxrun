#!/usr/bin/env python3
"""Fixture model. Never count this output as a real fresh-agent result."""

from __future__ import annotations

import sys as _person_sys
from pathlib import Path as _PersonPath
_person_root = next(p for p in _PersonPath(__file__).resolve().parents if (p / "base/person.py").is_file())
_person_sys.path.insert(0, str(_person_root))
from base import person as _fox_person
import json
import sys

request = json.load(sys.stdin)
if "answers" in request or "answer_key" in request or set(request) != {"instruction", "contracts", "questions"}:
    raise SystemExit(2)
answers = {
    "root-file":"inbox", "root-send":"no", "root-ask":_fox_person.name(), "root-load":"workspace", "root-touch":"secret",
    "workspace-file":"docs", "workspace-send":"no", "workspace-ask":_fox_person.name(), "workspace-load":"task", "workspace-touch":"no",
    "runtime-file":"agents", "runtime-send":"no", "runtime-ask":_fox_person.name(), "runtime-load":"agents", "runtime-touch":"no"
}
if len(sys.argv) > 1 and sys.argv[1] == "wrong":
    answers["root-file"] = "archive"
print(json.dumps({"answers": answers}))
