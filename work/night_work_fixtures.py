"""Synthetic tracker fixtures for small work command regressions."""

from __future__ import annotations

import sys as _person_sys
from pathlib import Path as _PersonPath
_person_root = next(p for p in _PersonPath(__file__).resolve().parents if (p / "base/person.py").is_file())
_person_sys.path.insert(0, str(_person_root))
from base import person as _fox_person
from contextlib import closing
import io
from pathlib import Path
import sqlite3
import tempfile
import unittest

import work

class WriterCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.db = self.root / 'tracker.sqlite'
        with closing(_fox_person.connect(self.db)) as db:
            db.executescript((Path(work.__file__).parent / 'blueprint.sql').read_text())
            db.execute("INSERT INTO tasks(id,title,ord) VALUES ('T1','Cedar Shop task',10)")
            db.execute("INSERT INTO decisions(id,name,status) VALUES ('order','Cedar Shop order','ruled')")
            db.commit()

    def call(self, *args):
        out, err = io.StringIO(), io.StringIO()
        code = work.run(['--db',str(self.db),'--receipt-root',str(self.root),*args],stdout=out,stderr=err)
        return code, out.getvalue(), err.getvalue()

    def sql(self, sql, values=()):
        with closing(_fox_person.connect(self.db)) as db:
            result = db.execute(sql,values).fetchall()
            db.commit()
            return result

    def assert_ok(self, result):
        self.assertEqual(0,result[0],result[2])

    def assert_refused_without_write(self, *args):
        before = self.db.read_bytes()
        result = self.call(*args)
        self.assertEqual(2,result[0],result)
        self.assertEqual(before,self.db.read_bytes())
        return result
