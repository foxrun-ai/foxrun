#!/usr/bin/env python3
"""Tests for the system SCHEMA.md page built by generate_pages.py (T681)."""

import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from base import generate_pages

RULES = Path(__file__).resolve().parents[2] / 'config/naming.md'


class SchemaPageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='generate-pages-')
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        (self.home / 'config').mkdir()
        with closing(sqlite3.connect(self.home / 'data.db')) as db:
            db.execute('CREATE TABLE object_types (name, module, storage_name, description)')
            db.execute('CREATE TABLE fields (object_type, field, field_type, required, description, ordinal)')
            db.execute("INSERT INTO object_types VALUES ('task', 'work', 'tasks', 'One task.')")
            db.execute("INSERT INTO fields VALUES ('task', 'id', 'text', 1, 'The id.', 1)")
            db.commit()

    def test_front_matter_comes_first_and_rules_keep_no_second_block(self):
        rules = '---\ntype: doc\nworkspace: old\ntimestamp: 2026-01-01T00:00:00-04:00\n---\n# Old\n\nRule.\n'
        (self.home / 'config/naming.md').write_text(rules)
        page = generate_pages.schema(self.home, timestamp='2026-10-18T12:00:00-04:00')
        self.assertTrue(page.startswith('---\ntype: doc\nworkspace: system\ntimestamp: 2026-10-18T12:00:00-04:00\n---\n# Schema: system\n'))
        self.assertEqual(page.count('\n---\n'), 1)
        self.assertNotIn('workspace: old', page)
        self.assertIn('| task | work | tasks | One task. |', page)

    def test_rebuild_with_no_change_keeps_the_timestamp(self):
        (self.home / 'config/naming.md').write_text('Rule.\n')
        first = generate_pages.schema(self.home, timestamp='2026-10-18T12:00:00-04:00')
        (self.home / 'SCHEMA.md').write_text(first)
        self.assertEqual(first, generate_pages.schema(self.home))

    def test_shipped_rules_hold_no_old_vault_text(self):
        raw = RULES.read_text()
        self.assertTrue(raw.startswith('---\ntype: doc\nworkspace: system\n'))
        text = generate_pages.strip_front_matter(raw)
        self.assertFalse(text.startswith('---'))
        for stale in ('retrofit', 'vault root', 'foxrun-dev', 'sample-shop', 'lane:', 'OKF'):
            self.assertNotIn(stale, text)


if __name__ == '__main__':
    unittest.main()
