"""Regression checks for stale dictionary fields and state-only change events."""
from __future__ import annotations

import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'base'), str(ROOT / 'base/tests'), str(ROOT / 'work'), str(ROOT / 'events')]
from base.tests.support import setup
setup()

from contextlib import closing, redirect_stdout
import io
import re
import sqlite3
import tempfile
import unittest

from base import apply_dictionary
from core import build, connect, guard_sql, load, EVENTS
from fixtures import Fixtures

# People and pack tables come from their add-ons' own blueprints (g-business-packs-do-not-ship).
from base.tests.addons import BLUEPRINT
CONTEXT = {'writer': 'feeder', 'source': 'made-up upkeep fixtures', 'import': 1,
           'workspace': 'system-workspace', 'actor': 'sol-test', 'session': 'fake-session'}


class DictionaryColumnsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'tracker.db'
        self.backups = Path(self.temp.name) / 'backups'
        with closing(sqlite3.connect(self.path)) as db:
            db.executescript((ROOT / 'work/blueprint.sql').read_text())
        apply_dictionary.apply(self.path, self.backups)

    def test_old_rank_is_repaired_and_repeated_apply_keeps_business_rows(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("INSERT INTO functions(id,name,tags) VALUES ('fixture','Made-up function','rank-1')")
            db.execute("INSERT INTO fields(object_type,field,ordinal,field_type,description,source) VALUES ('functions','rank',99,'number','Obsolete rank','pr-g-function-order')")
            db.execute("UPDATE fields SET ordinal=99 WHERE object_type='runs' AND field='session'")
            db.commit()
            self.assertEqual(['functions: functions.rank'], apply_dictionary.dictionary_column_errors(db))
        apply_dictionary.apply(self.path, self.backups)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual([], apply_dictionary.dictionary_column_errors(db))
            self.assertEqual(('fixture','Made-up function','rank-1'), db.execute('SELECT id,name,tags FROM functions').fetchone())
            self.assertEqual(0, db.execute("SELECT count(*) FROM fields WHERE object_type='functions' AND field='rank'").fetchone()[0])
        before = self.path.read_bytes()
        self.assertFalse(apply_dictionary.apply(self.path, self.backups)['backup_created'])
        self.assertEqual(before, self.path.read_bytes())

    def test_check_covers_installed_tables_outside_current_objects_and_is_read_only(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('CREATE TABLE fixture_table(id TEXT)')
            db.execute("INSERT INTO object_types(name,container,module,database_type,storage_name,description,source) VALUES ('fixture-alias','collection','work','table','fixture_table','Made-up table','fixture')")
            db.execute("INSERT INTO fields(object_type,field,ordinal,field_type,description,source) VALUES ('fixture-alias','missing',1,'text','Missing column','fixture')")
            db.commit()
            self.assertEqual(['fixture-alias: fixture_table.missing'], apply_dictionary.dictionary_column_errors(db))
            with self.assertRaisesRegex(ValueError, 'fixture_table.missing'):
                apply_dictionary.verify(db, set())
        before = self.path.read_bytes()
        with redirect_stdout(io.StringIO()):
            self.assertEqual(2, apply_dictionary.run(['--db', str(self.path), '--check']))
        self.assertEqual(before, self.path.read_bytes())


class StateChangeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.path = Path(cls.temp.name) / 'blueprint.db'
        build(cls.path, BLUEPRINT)
        cls.targets, cls.columns = load(BLUEPRINT)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.db = connect(self.path, CONTEXT)
        self.addCleanup(self.db.close)
        self.fixture = Fixtures(self.db, self.targets, self.columns)

    def events(self, kind, identity):
        return [dict(row) for row in self.db.execute('SELECT * FROM work_changes WHERE subject_type=? AND subject_id=? ORDER BY seq', (kind, identity))]

    def test_generated_events_match_state_and_required_proof_fields(self):
        sql = guard_sql(self.targets, self.columns)
        actual = set(re.findall(r'CREATE TRIGGER "([^"]+_changed)"', sql))
        expected = {t['name'] + '_' + field + '_changed' for t in self.targets
                    if t['kind'] == 'table' and t['name'] not in EVENTS
                    for field in t.get('state_write_columns', [])
                    if any(c['table'] == t['name'] and c['column'] == field for c in self.columns)}
        expected.add('people_messages_source_message_id_changed')
        expected.update(c['table'] + '_' + c['column'] + '_changed' for c in self.columns
                        if c['table'] in ('people_drafts','people_draft_facts')
                        and c['column'] not in ('id','version','updated_at'))
        self.assertEqual(expected, actual)
        for target in self.targets:
            if target.get('database_type') in ('mirror', 'trend'):
                self.assertNotIn('CREATE TRIGGER "' + target['name'] + '_created"', sql)

    def test_mirror_insert_and_source_refresh_create_no_change_events(self):
        cases = [('people_messages', 'message', 'text', 'Made-up message'),
                 ('treasury_transactions', 'transaction', 'memo', 'Made-up memo'),
                 ('amazon_listings', 'listing', 'title', 'Made-up title')]
        for table, kind, field, value in cases:
            with self.subTest(table=table):
                identity = self.fixture.row(table)
                self.assertEqual([], self.events(kind, identity))
                self.db.execute('UPDATE "' + table + '" SET "' + field + '"=? WHERE id=?', (value, identity))
                self.assertEqual([], self.events(kind, identity))
                if table == 'people_messages':
                    self.db.execute("UPDATE people_messages SET source_message_id='made-up refreshed id' WHERE id=?", (identity,))
                    self.assertEqual([], self.events(kind, identity))

    def test_conversation_logs_only_actual_status_changes(self):
        identity = self.fixture.row('people_conversations', status='open')
        self.assertEqual([], self.events('conversation', identity))
        self.db.execute("UPDATE people_conversations SET title='Made-up refresh',status=status WHERE id=?", (identity,))
        self.assertEqual([], self.events('conversation', identity))
        self.db.execute("UPDATE people_conversations SET status='snoozed',snoozed_until='2026-12-01' WHERE id=?", (identity,))
        event, = self.events('conversation', identity)
        self.assertEqual(('status','open','snoozed','sol-test','fake-session'),
                         tuple(event[k] for k in ('field','old_value','new_value','actor','session')))
        self.db.execute('UPDATE people_conversations SET status=status WHERE id=?', (identity,))
        self.assertEqual(1, len(self.events('conversation', identity)))

    def test_record_birth_state_event_and_rollback_keep_sequence_atomic(self):
        identity = self.fixture.row('work_tasks', status='todo')
        self.assertEqual(1, len(self.events('task', identity)))
        self.db.execute("UPDATE work_tasks SET title='Made-up edit' WHERE id=?", (identity,))
        self.assertEqual(1, len(self.events('task', identity)))
        before = self.db.execute('SELECT value FROM _foxrun_sequence').fetchone()[0]
        self.db.execute('SAVEPOINT state_change')
        self.db.execute("UPDATE work_tasks SET status='in-progress' WHERE id=?", (identity,))
        self.assertEqual(before + 1, self.db.execute('SELECT value FROM _foxrun_sequence').fetchone()[0])
        self.assertEqual('status', self.events('task', identity)[-1]['field'])
        self.db.execute('ROLLBACK TO state_change')
        self.db.execute('RELEASE state_change')
        self.assertEqual(before, self.db.execute('SELECT value FROM _foxrun_sequence').fetchone()[0])
        self.assertEqual('todo', self.db.execute('SELECT status FROM work_tasks WHERE id=?', (identity,)).fetchone()[0])
        self.assertEqual(1, len(self.events('task', identity)))


if __name__ == '__main__':
    unittest.main()
