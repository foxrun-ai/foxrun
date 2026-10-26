"""Check events/blueprint.sql against its sources.

Run from the system folder: python3 -m unittest events/tests/test_blueprint.py

The five product tables must equal base/schema.sql, with only the table name changed.
The two Jev tables must have the columns of the Jev skill's own file.
"""
from __future__ import annotations

import re
import sqlite3
import sys
import unittest
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'base/core.py').is_file())
sys.path[:0] = [str(ROOT)]
from base.tests.support import setup
setup()
from base import check_blueprints, person

BLUEPRINT = ROOT / 'events/blueprint.sql'
SCHEMA = ROOT / 'base/schema.sql'
JEV = ROOT / 'skills/jev/references/agent-os-migration.sql'
PRODUCT = {'work_changes': 'events_changes', 'work_comments': 'events_comments',
           'work_attachments': 'events_attachments', 'base_receipts': 'events_receipts',
           'work_runs': 'events_runs'}
JEV_TABLES = {'jev_runs': 'events_jev_runs', 'jev_feedback': 'events_jev_feedback'}


def statements(text):
    text = re.sub(r'--[^\n]*', '', text)
    return [' '.join(s.split()) for s in re.split(r';\s*\n', text) if s.strip()]


def created(text, kind):
    """Map each created name to its statement. kind is TABLE or INDEX."""
    found = {}
    for s in statements(text):
        m = re.match(r'CREATE (?:UNIQUE )?' + kind + r' (?:IF NOT EXISTS )?"?(\w+)"?', s)
        if m:
            found[m.group(1)] = s.rstrip(';').replace(' IF NOT EXISTS', '', 1)
    return found


def load(path_or_text):
    db = person.connect(':memory:')
    db.execute('PRAGMA foreign_keys=ON')
    db.executescript(path_or_text.read_text() if isinstance(path_or_text, Path) else path_or_text)
    return db


class EventsBlueprint(unittest.TestCase):
    def test_it_loads_twice_and_makes_the_seven_tables(self):
        db = load(BLUEPRINT)
        db.executescript(BLUEPRINT.read_text())
        names = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        self.assertEqual(names, set(PRODUCT.values()) | set(JEV_TABLES.values()))
        db.close()

    def test_product_tables_equal_base_schema_but_for_the_name(self):
        product, mine = created(SCHEMA.read_text(), 'TABLE'), created(BLUEPRINT.read_text(), 'TABLE')
        for old, new in PRODUCT.items():
            self.assertEqual(mine[new], product[old].replace('"' + old + '"', '"' + new + '"'), new)

    def test_indexes_equal_base_schema_but_for_the_name(self):
        product, mine = created(SCHEMA.read_text(), 'INDEX'), created(BLUEPRINT.read_text(), 'INDEX')
        expected = {}
        for name, statement in product.items():
            for old, new in PRODUCT.items():
                if ' ON "' + old + '"' in statement:
                    expected[name.replace(old, new, 1)] = statement.replace(old, new)
        self.assertEqual({k: v for k, v in mine.items() if k.startswith('events_')}, expected)

    def test_jev_tables_have_the_columns_of_the_jev_skill(self):
        if not JEV.is_file():
            self.skipTest('the Jev skill is not installed')
        text = re.sub(r'^\s*(BEGIN IMMEDIATE|COMMIT);\s*$', '', JEV.read_text(), flags=re.M)
        skill, mine = load(text), load(BLUEPRINT)
        for old, new in JEV_TABLES.items():
            a = [tuple(r)[1:] for r in skill.execute('PRAGMA table_info("' + old + '")')]
            b = [tuple(r)[1:] for r in mine.execute('PRAGMA table_info("' + new + '")')]
            self.assertTrue(a)
            self.assertEqual(a, b, new)
        skill.close()
        mine.close()

    def test_no_name_is_made_by_another_blueprint(self):
        paths = [ROOT / 'base/dictionary.sql']
        for manifest in sorted(ROOT.glob('*/install.json')) + sorted(ROOT.glob('modules/*/install.json')):
            if (manifest.parent / 'blueprint.sql').is_file():
                paths.append(manifest.parent / 'blueprint.sql')
        self.assertIn(BLUEPRINT, paths)
        mine = [f for f in check_blueprints.check_blueprints(paths)
                if f.file == str(BLUEPRINT) or str(BLUEPRINT) in f.detail]
        self.assertEqual(mine, [])

    def test_a_row_needs_a_workspace_of_this_installation(self):
        db = load(BLUEPRINT)
        row = ("INSERT INTO events_comments (action,actor,body,recorded_at,session,subject_id,subject_type,workspace) "
               "VALUES ('commented','tester','A note.','2026-10-13T12:00:00Z','s1',1,'task',?)")
        db.execute(row, (person.configured_workspaces()[0],))
        with self.assertRaises(sqlite3.IntegrityError):
            db.execute(row, ('not-a-workspace',))
        with self.assertRaises(sqlite3.IntegrityError):
            db.execute(row.replace("'commented'", "'liked'"), (person.configured_workspaces()[0],))
        db.close()


if __name__ == '__main__':
    unittest.main()
