#!/usr/bin/env python3
"""people: checked writes for People tables."""

from __future__ import annotations
import sys
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'base/table.py').is_file())
sys.path.insert(0, str(ROOT / 'base'))
from table import CommandConfig, main
import table
FIXTURE = next(p for p in Path(__file__).resolve().parents if (p / 'cedar-fixture.json').is_file())
table.MODULES_ROOT = FIXTURE

main(CommandConfig(
    module="people",
    writable=(
        "persons", "organizations", "organization_memberships", "handles",
        "threads", "participants", "pipelines", "pipeline_stages",
        "opportunities", "interactions", "meetings", "agreements",
    ),
    mirrors={"messages": "small-talk is its feeder"},
))
