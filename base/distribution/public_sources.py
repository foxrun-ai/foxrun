"""Remove private source bindings from a public copy. Preserve model names and constraints."""

from __future__ import annotations
import sys
from pathlib import Path
_product_root = next(p for p in Path(__file__).resolve().parents if (p / "base/person.py").is_file())
sys.path.insert(0, str(_product_root))
from base import person as _fox_person
import json
import re

OWNER = re.compile(r'(?<![\w])(?:' + '|'.join(re.escape(t) for t in _fox_person.private_terms()) + r')(?![\w])', re.I)

def text(value):
    value = OWNER.sub('owner', value)
    return value

def source(destination, raw):
    value = raw.decode('utf-8')
    if destination == 'agent-team/tools/render_capabilities.py':
        # The public generator refers to model evidence, never a private business file.
        value = OWNER.sub('model', value)
    return text(value).encode()

def rows(values):
    def clean(value):
        if isinstance(value, dict):
            return {key: clean(item) for key, item in value.items()}
        if isinstance(value, list):
            return [clean(item) for item in value]
        if isinstance(value, str):
            return text(value)
        return value
    return [clean(row) for row in values]
