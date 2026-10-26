"""Every ruling id cited in a blueprint is a decision row; no scrubber mark is left in a blueprint.

The blueprint cites rulings by the id they had when it was written. Since then the
decision rows took a prefix: plain ids became g-<id>, and pr-<id> became pr-g-<id>.
A citation counts when the row exists under its id or under that later form.
@person@ is the configured person's name. The row check needs decision rows; a fresh
home has none, so it skips there and runs on a home with history.

Rerun: python3 -m unittest base.tests.test_blueprint_rulings
"""
import json
from pathlib import Path
import re
import sqlite3
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from base import paths, person  # noqa: E402

BLUEPRINT = ROOT / 'base/blueprint'
# Cited values that are not a decision row, with the reason.
NOT_A_ROW = {
    'product definition': 'dictionary-extension.json names the product definition as its authority',
    'source-note-dependency-rule': 'cited since v13; no decision row has this id, name, or statement',
}


def cited():
    found = {}

    def walk(value, source):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in ('ruling', 'rulings') and isinstance(item, list):
                    for ruling in item:
                        found.setdefault(ruling, set()).add(source)
                else:
                    walk(item, source)
        elif isinstance(value, list):
            for item in value:
                walk(item, source)

    for path in sorted(BLUEPRINT.glob('*.json*')):
        lines = path.read_text().splitlines() if path.suffix == '.jsonl' else [path.read_text()]
        for line in lines:
            if line.strip():
                walk(json.loads(line), path.name)
    return found


def forms(ruling):
    if '@person@' in ruling:
        ruling = ruling.replace('@person@', person.name().lower())
    yield ruling
    yield 'g-' + ruling
    if ruling.startswith('pr-'):
        yield 'pr-g-' + ruling[3:]


class BlueprintRulings(unittest.TestCase):
    def test_no_scrubber_mark_or_sample_name_in_a_ruling(self):
        for ruling, sources in cited().items():
            self.assertNotIn('[TEST-', ruling, sorted(sources))
            self.assertNotIn('sample-', ruling, sorted(sources))
        for path in BLUEPRINT.glob('*.json*'):
            self.assertNotIn('[TEST-', path.read_text(), path.name)

    def test_every_cited_ruling_is_a_decision_row(self):
        database = paths.database()
        try:
            with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as db:
                rows = {r[0] for r in db.execute('SELECT id FROM decisions')}
        except sqlite3.Error:
            rows = set()
        if not rows:
            self.skipTest('no decision rows in ' + str(database))
        missing = []
        for ruling, sources in sorted(cited().items()):
            if ruling in NOT_A_ROW or re.fullmatch(r'@\w+@', ruling):
                continue  # a value set at install from config/person.json import_marks
            if not any(form in rows for form in forms(ruling)):
                missing.append((ruling, sorted(sources)))
        self.assertEqual(missing, [])


if __name__ == '__main__':
    unittest.main()
