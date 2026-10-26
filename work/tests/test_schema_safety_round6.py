"""The schema command retains backup, verification, receipts, and exact undo."""

import sys as _fox_sys
from pathlib import Path as _FoxPath
_fox_root = _FoxPath(__file__).resolve().parents[2]
_fox_sys.path.insert(0, str(_fox_root))
from base.tests.support import setup as _fox_test_setup
_fox_test_setup()
import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing, redirect_stdout
from pathlib import Path
from unittest.mock import patch
import apply_program_schema as command

class SchemaSafety(unittest.TestCase):
    def test_schema_command_backup_receipt_verify_and_undo(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); path = root / 'work.db'
            with closing(sqlite3.connect(path)) as db:
                db.executescript((command._person_root / 'work/blueprint.sql').read_text())
                db.execute('ALTER TABLE runs DROP COLUMN session')
                db.execute("INSERT INTO tasks(id,title,status) VALUES('T1','Keep this','todo')")
                db.commit()
            original = path.read_bytes()
            args = ['--db',str(path),'--receipt-root',str(root / 'receipts'),'--backup-dir',str(root / 'backups')]
            out = io.StringIO()
            with redirect_stdout(out): self.assertEqual(command.run(args), 0)
            report = json.loads(out.getvalue())
            self.assertTrue(report['backup_created'])
            self.assertTrue(all(report['checks'].values()))
            with closing(sqlite3.connect(report['backup'])) as saved:
                self.assertEqual(saved.execute('SELECT id,title FROM tasks').fetchall(), [('T1','Keep this')])
                self.assertNotIn('session', [r[1] for r in saved.execute('PRAGMA table_info(runs)')])
            self.assertTrue((root / 'receipts/state').is_dir())
            with redirect_stdout(io.StringIO()): self.assertEqual(command.run(args + ['--undo',report['backup']]), 0)
            self.assertEqual(path.read_bytes(), Path(report['backup']).read_bytes())

    def test_verification_failure_keeps_database_exact(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'work.db'
            with closing(sqlite3.connect(path)) as db:
                db.executescript((command._person_root / 'work/blueprint.sql').read_text())
            original = path.read_bytes()
            with patch.object(command, 'verify_schema_only', side_effect=ValueError('injected verification failure')):
                self.assertEqual(command.run(['--db',str(path),'--receipt-root',folder]), 2)
            self.assertEqual(path.read_bytes(), original)
