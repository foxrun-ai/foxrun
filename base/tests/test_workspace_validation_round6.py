"""Workspace constraints use installation data, including list values."""

import sys as _fox_sys
from pathlib import Path as _FoxPath
_fox_root = _FoxPath(__file__).resolve().parents[2]
_fox_sys.path.insert(0, str(_fox_root))
from base.tests.support import setup as _fox_test_setup
_fox_test_setup()
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from base import person
from base import core

class WorkspaceValidation(unittest.TestCase):
    def test_configured_people_known_unknown_and_lists(self):
        owners = [('person',['cedar-shop','system-workspace','sample-finance','personal-workspace','career-workspace','venture-workspace','runtime-workspace']), ('avery',['cedar-lab'])]
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); (root/'config').mkdir()
            for owner, workspaces in owners:
                (root/'config/person.json').write_text(json.dumps({'name':owner,'workspaces':workspaces}))
                with patch.dict(os.environ, {'FOXRUN_HOME':str(root),'FOXRUN_PERSON':owner}):
                    # People tables come from Small Talk's own blueprint (g-people-ships-with-small-talk).
                    from base.tests.addons import folders
                    targets,columns=core.load(Path(core.__file__).parent/'blueprint',addons=folders())
                    workspace=next(c for c in columns if c['table']=='work_tasks' and c['column']=='workspace')
                    with closing(person.connect(':memory:')) as db:
                        db.execute('CREATE TABLE probe ('+core.field_sql(workspace,[])+')')
                        for known in workspaces: db.execute('INSERT INTO probe VALUES(?)',(known,))
                        self.assertEqual(db.execute('SELECT count(*) FROM probe').fetchone()[0],len(workspaces))
                        with self.assertRaises(sqlite3.IntegrityError): db.execute("INSERT INTO probe VALUES('unknown-workspace')")
                        with self.assertRaises(sqlite3.IntegrityError): db.execute("UPDATE probe SET workspace='unknown-workspace'")
                    portfolio=next(c for c in columns if c['table']=='work_functions' and c['column']=='workspace')
                    with closing(person.connect(':memory:')) as db:
                        db.execute('CREATE TABLE scope ('+core.field_sql(portfolio,[])+')')
                        db.execute("INSERT INTO scope VALUES('foxrun')")
                        with self.assertRaises(sqlite3.IntegrityError): db.execute("INSERT INTO scope VALUES('unknown-workspace')")
                    guards=core.guard_sql(targets,columns)
                    for table in ('people_conversations','people_messages'):
                        with closing(person.connect(':memory:')) as db:
                            db.execute('CREATE TABLE '+table+' (workspace_tags TEXT)')
                            for line in guards.splitlines():
                                if '"'+table+'_workspace_tags_' in line and 'invalid list pick' in line: db.execute(line)
                            db.execute('INSERT INTO '+table+' VALUES(?)',(json.dumps(workspaces),))
                            with self.assertRaises(sqlite3.IntegrityError): db.execute('INSERT INTO '+table+' VALUES(?)',('["unknown-workspace"]',))
                            with self.assertRaises(sqlite3.IntegrityError): db.execute('UPDATE '+table+' SET workspace_tags=?',('["unknown-workspace"]',))

    def test_table_only_install_and_missing_install_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'FOXRUN_HOME':folder}):
            with closing(person.connect(':memory:')) as db:
                db.execute('CREATE TABLE workspaces(id TEXT PRIMARY KEY)')
                db.execute("INSERT INTO workspaces VALUES('cedar-lab')")
                db.execute('CREATE TABLE probe(workspace TEXT CHECK(foxrun_workspace_allowed(workspace)))')
                db.execute("INSERT INTO probe VALUES('cedar-lab')")
                with self.assertRaises(sqlite3.IntegrityError): db.execute("INSERT INTO probe VALUES('unknown-workspace')")
            with closing(person.connect(':memory:')) as db:
                db.execute('CREATE TABLE probe(workspace TEXT CHECK(foxrun_workspace_allowed(workspace)))')
                with self.assertRaises(sqlite3.IntegrityError): db.execute("INSERT INTO probe VALUES('cedar-lab')")

    def test_sample_install_uses_its_own_roster(self):
        from base.distribution import sample_workspace as sample
        source=Path(person.__file__).parent
        fixture=json.loads((source/'distribution/sample/rows.json').read_text())
        with closing(sample.build_database(source,fixture)) as db:
            self.assertGreater(db.execute('SELECT count(*) FROM work_tasks').fetchone()[0],0)
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("UPDATE work_tasks SET workspace='unknown-workspace'")
