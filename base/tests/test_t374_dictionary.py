"""T374: dictionary text upgrades existing installs without changing task keys."""

from __future__ import annotations

import sys as _fox_sys
from pathlib import Path as _FoxPath
_fox_root = next(p for p in _FoxPath(__file__).resolve().parents if (p / 'base/core.py').is_file())
_fox_sys.path[:0] = [str(_fox_root / p) for p in ('base', 'work', 'events', 'decisions', 'memory', 'people', 'design', 'capture')]
_fox_sys.path.insert(0, str(_fox_root))
from base.tests.support import setup as _fox_test_setup
_fox_test_setup()
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

import apply_dictionary

TEXT = ("Prevents repeated intake from creating the same task twice. The reserved session-holding-task "
        "value marks the session holding task; only session_run setup and backfill-key may set it.")

class HoldingDictionaryTests(unittest.TestCase):
    def test_upgrade_dictionary_without_required_column(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'tracker.sqlite'
            with closing(sqlite3.connect(path)) as db:
                db.executescript((apply_dictionary.BASE.parent / 'work/blueprint.sql').read_text())
                db.executescript(apply_dictionary.DICTIONARY_SQL.read_text())
                db.execute('DROP VIEW v_dictionary')
                db.execute('ALTER TABLE fields DROP COLUMN required')
                db.commit()
            apply_dictionary.apply(path, root / 'backups')
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(TEXT, db.execute("SELECT description FROM fields WHERE object_type='tasks' AND field='idempotency_key'").fetchone()[0])
                self.assertEqual(1, db.execute("SELECT required FROM v_dictionary WHERE object_type='tasks' AND field='id'").fetchone()[0])

    def test_keep_written_description_and_repeat_without_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "tracker.sqlite"
            with closing(sqlite3.connect(path)) as db:
                db.executescript((apply_dictionary.BASE.parent / "work/blueprint.sql").read_text())
                db.execute("INSERT INTO tasks(id,title,idempotency_key) VALUES ('T9','Free title','session-holding-task')")
                db.commit()
            apply_dictionary.apply(path, root / "backups")
            with closing(sqlite3.connect(path)) as db:
                db.execute("UPDATE fields SET description='Old text' WHERE object_type='tasks' AND field='idempotency_key'")
                db.commit()
            apply_dictionary.apply(path, root / "backups")
            with closing(sqlite3.connect(path)) as db:
                # T712: the writer keeps written text. A text upgrade ships as a guarded seed UPDATE, never as a sweep.
                self.assertEqual('Old text', db.execute("SELECT description FROM fields WHERE object_type='tasks' AND field='idempotency_key'").fetchone()[0])
                self.assertEqual(('Free title','session-holding-task'), db.execute("SELECT title,idempotency_key FROM tasks").fetchone())
            before = path.read_bytes()
            report = apply_dictionary.apply(path, root / "backups")
            self.assertFalse(report['backup_created'])
            self.assertEqual(before, path.read_bytes())

if __name__ == '__main__':
    unittest.main()
