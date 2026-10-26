"""Proof that the core works for another person."""
from contextlib import closing, redirect_stdout, redirect_stderr
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


import sys as _fox_sys
from pathlib import Path as _FoxPath
_fox_root = _FoxPath(__file__).resolve().parents[2]
_fox_sys.path.insert(0, str(_fox_root))
from base.tests.support import setup as _fox_test_setup
_fox_test_setup()
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'base')]
from base import person
from base.install_system import install_configuration


class PersonConfiguration(unittest.TestCase):
    def test_config_file_env_priority_and_missing_error(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            env = {'FOXRUN_HOME': str(root)}
            with patch.dict(os.environ, env):
                previous = os.environ.pop('FOXRUN_PERSON', None)
                try:
                    with self.assertRaisesRegex(person.PersonError, 'Set FOXRUN_PERSON'):
                        person.name()
                    self.assertEqual(install_configuration(root, 'avery'), ['catalog.yaml', 'models.yaml', 'modules.yaml', 'person.json'])
                    self.assertEqual(person.name(), 'avery')
                    self.assertEqual(person.display_name(), 'Avery')
                    os.environ['FOXRUN_PERSON'] = 'blake'
                    self.assertEqual(person.name(), 'blake')
                    self.assertEqual(install_configuration(root, 'blake'), [])
                    self.assertEqual(json.loads((root / 'config/person.json').read_text())['name'], 'avery')
                finally:
                    if previous is not None:
                        os.environ['FOXRUN_PERSON'] = previous
                    else:
                        os.environ.pop('FOXRUN_PERSON', None)

    def test_original_case_rules_apply_to_mixed_case_configured_name(self):
        with patch.dict(os.environ, {'FOXRUN_PERSON': 'Avery'}):
            sql = person.render_sql("SELECT lower('AVERY')='@person@', 'Avery'='@person@', 'avery'='@person@'")
            with closing(sqlite3.connect(':memory:')) as db:
                self.assertEqual(db.execute(sql).fetchone(), (1, 1, 0))

    def test_leads_come_from_config(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'config').mkdir()
            (root / 'config/person.json').write_text('{"name":"avery","leads":["director"]}')
            with patch.dict(os.environ, {'FOXRUN_HOME': str(root)}):
                self.assertEqual(person.leads(), ('director',))

    def test_avery_core_commands_seed_and_handoff(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            env = dict(os.environ, FOXRUN_PERSON='avery', FOXRUN_HOME=str(root / 'system'),
                       FOXRUN_PORTFOLIO=str(root / 'portfolio'), FOXRUN_STATE=str(root / 'state'))
            # Run in a fresh Python process, so import-time person constants cannot retain the incumbent owner.
            code = r'''
from contextlib import closing, redirect_stdout
import io, json, sys
from datetime import datetime, timezone
from pathlib import Path
from base import person
from base.build_database import build_database
from base import lookup
import work
import handoff_check as hc
root=Path(sys.argv[1]).resolve();db=root/'tracker.db';receipts=root/'receipts';receipts.mkdir()
# g-people-ships-with-small-talk (231264d): the core builds no people tables.
build_database(db,'work',actor='avery')
with closing(person.connect(db)) as conn:
    conn.executescript((Path(lookup.__file__).parent/'dictionary.sql').read_text())
    conn.executescript((Path(lookup.__file__).parent/'dictionary-seed.sql').read_text())
    assert conn.execute('PRAGMA foreign_key_check').fetchall()==[]
    assert conn.execute('SELECT count(*) FROM object_types').fetchone()[0]>0
common=['--db',str(db),'--receipt-root',str(receipts)]
# g-every-task-carries-the-six-fields-a-spec-is-a-parent-task: create needs the six fields.
six=['--problem','p','--job-when','w','--job-want','x','--job-so','s','--body','b','--context','c','--where',str(db)]
assert work.run(['create','--id','T1','--title','Avery task','--acceptance','one proof',*six,'--by','avery',*common])==0
assert work.run(['task-update','T1','--owner','avery','--note','owner configured','--by','avery',*common])==0
assert work.run(['decision-add','--id','keep-wiki','--name','Keep wiki','--statement','Keep the workspace wiki.','--person-words','Avery: keep the workspace wiki folder for all durable knowledge.','--by','avery',*common])==0
assert work.run(['approval-add','T1','--call','approve','--person-words','Avery: approved.','--source','comment:1','--by','avery',*common])==0
assert work.run(['comment','T1','Avery: keep the workspace wiki folder for all durable knowledge.','--by','avery',*common])==0
with closing(person.connect(db)) as conn:
    assert conn.execute('SELECT owner FROM tasks WHERE id="T1"').fetchone()==('avery',)
    assert conn.execute('SELECT person_words FROM decisions').fetchone()==('Avery: keep the workspace wiki folder for all durable knowledge.',)
    assert conn.execute('SELECT person_words FROM approvals').fetchone()==('Avery: approved.',)
    assert conn.execute("SELECT body FROM comments WHERE body LIKE 'Avery:%'").fetchone()==('Avery: keep the workspace wiki folder for all durable knowledge.',)
assert hc.PERSON_PREFIX.match('Avery: approved.')
assert not hc.PERSON_PREFIX.match('Someone Else: approved.')
data=hc.Extract("avery", root/"session.jsonl");data.assistant_text="For task T1.";data.add_user_turn('Keep the workspace wiki folder for all durable knowledge.', datetime.now(timezone.utc).isoformat())
hc.mark_recorded(data,(db,))
assert data.person[0]['recorded']
assert lookup.dictionary(None)[0]
print('avery proof passed')
'''
            env['PYTHONPATH'] = os.pathsep.join([str(ROOT), str(ROOT / 'base'), str(ROOT / 'work'), str(ROOT / 'events'), str(ROOT / 'decisions'), str(ROOT / 'memory'), env.get('PYTHONPATH', '')])
            result = subprocess.run(['/usr/bin/python3', '-B', '-c', code, str(root)], env=env,
                                    cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('avery proof passed', result.stdout)
