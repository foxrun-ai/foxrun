"""Run the SQLite backup child alone, without the macOS sandbox."""

import sys as _fox_sys
from pathlib import Path as _FoxPath
_fox_root = _FoxPath(__file__).resolve().parents[2]
_fox_sys.path.insert(0, str(_fox_root))
from base.tests.support import setup as _fox_test_setup
_fox_test_setup()
from contextlib import closing
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import reader_check

class BackupChild(unittest.TestCase):
    def test_child_string_is_self_contained(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); source = root / 'source.db'; destination = root / 'copy.db'
            with closing(sqlite3.connect(source)) as db:
                db.execute('CREATE TABLE facts(value TEXT)')
                db.execute("INSERT INTO facts VALUES('kept')"); db.commit()
            calls = []
            def standalone(argv, *args):
                calls.append(argv)
                process = subprocess.run(argv, capture_output=True, text=True)
                self.assertEqual(process.returncode, 0, process.stderr)
                return process.returncode
            with patch.object(reader_check, 'sandbox_command', side_effect=standalone):
                reader_check.backup(source, destination, root)
            self.assertEqual(len(calls), 1)
            with closing(sqlite3.connect(destination)) as db:
                self.assertEqual(db.execute('SELECT value FROM facts').fetchall(), [('kept',)])
                self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
