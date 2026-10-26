"""Check the reviewed memory schema with Python's SQLite library only."""
import importlib.util
import os
import re
import sqlite3
import tempfile
import unittest
from pathlib import Path

MEMORY = Path(__file__).resolve().parents[1]
ROOT = MEMORY.parent
REFERENCE = Path(os.environ.get('FOX_MEMORY_REFERENCE_ROOT', str(ROOT)))
spec = importlib.util.spec_from_file_location('memory_digest', MEMORY / 'source_digest.py')
digest = importlib.util.module_from_spec(spec)
spec.loader.exec_module(digest)


def tables(text):
    text = re.sub(r'--[^\n]*', '', text)
    found = {}
    for s in text.split(';'):
        m = re.match(r'\s*CREATE TABLE (?:IF NOT EXISTS )?"?(\w+)"?', s)
        if m:
            found[m.group(1)] = ' '.join(s.split()).replace(' IF NOT EXISTS', '', 1)
    return found


class MemorySchema(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.db.create_function('foxrun_workspace_allowed', 1, lambda w: w == 'fixture')
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.executescript((MEMORY / 'blueprint.sql').read_text())

    def tearDown(self):
        self.db.close()

    def source(self, **change):
        row = dict(workspace='fixture',number='S1',weight='light',path='a',sha256='a'*64,
                   captured_by='capture',captured_at='2026-10-14T00:00:00Z',trusted=0,status='ok')
        row.update(change)
        return self.db.execute('INSERT INTO memory_sources ('+','.join(row)+') VALUES ('+
            ','.join('?' for _ in row)+')', list(row.values())).lastrowid

    def test_idempotent_four_tables(self):
        self.db.executescript((MEMORY / 'blueprint.sql').read_text())
        self.assertEqual({r[0] for r in self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")},
            {'memory_lessons','memory_sources','memory_evidence','memory_rollups'})

    def test_lessons_preserve_reviewed_product_definition(self):
        actual = tables((MEMORY / 'blueprint.sql').read_text())['memory_lessons']
        reference = tables((REFERENCE / 'base/schema.sql').read_text())['work_lessons']
        self.assertEqual(actual, reference.replace('"work_lessons"','"memory_lessons"'))

    def test_required_hash_for_both_weights_and_validation(self):
        self.source()
        for weight in ('light','heavy'):
            for bad in (None, '', 'abc', 'A'*64, 'x'*64):
                with self.subTest(weight=weight, hash=bad), self.assertRaises(sqlite3.IntegrityError):
                    self.source(number='other',path='other',weight=weight,sha256=bad)

    def test_keys_metadata_and_workspace_constraints(self):
        self.source(canonical_url='https://example.test/one')
        bad = [dict(number='S2'),dict(path='b'),
               dict(number='S2',path='b',canonical_url='https://example.test/one')]
        for field,value in [('trusted',2),('status','fine'),('weight','big'),('workspace','missing'),
                            ('captured_at','invalid'),('tags','{}'),('details','invalid')]:
            bad.append(dict(number='S2',path='b',**{field:value}))
        for row in bad:
            with self.subTest(row=row), self.assertRaises(sqlite3.IntegrityError):
                self.source(**row)
        self.source(number='S2',weight='heavy',sha256='b'*64)

    def test_evidence_requires_existing_source_and_prevents_deletion(self):
        source = self.source()
        insert = 'INSERT INTO memory_evidence(subject_type,subject_id,source,actor,created_at) VALUES(?,?,?,?,?)'
        args = ('decision',1,source,'keeper','2026-10-14T00:00:00Z')
        self.db.execute(insert,args)
        for bad in (args,('lesson',1,source+1,'keeper',args[-1]),('task',1,source,'keeper',args[-1])):
            with self.assertRaises(sqlite3.IntegrityError):
                self.db.execute(insert,bad)
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute('DELETE FROM memory_sources WHERE id=?',(source,))

    def test_heavy_tree_hash_catches_previous_exclusions(self):
        with tempfile.TemporaryDirectory(dir=MEMORY / 'tests') as folder:
            root = Path(folder)
            for name in ('build','dist','.cache','node_modules'):
                (root/name).mkdir()
                (root/name/'captured').write_text('one')
            first = digest.digest_tree(root)
            self.source(weight='heavy',sha256=first)
            for name in ('build','dist','.cache','node_modules'):
                p = root/name/'captured'
                p.write_text('two')
                self.assertEqual(digest.check_source(root,first),'changed')
                p.write_text('one')

    def test_rollups_unique_even_for_empty_action(self):
        insert = ('INSERT INTO memory_rollups(workspace,period,starts_on,event_table,subject_type,'
                  'action,event_count,last_seq,built_at) VALUES(?,?,?,?,?,?,?,?,?)')
        args = ('fixture','week','2026-10-12','events_changes','task',None,4,9,'2026-10-14T00:00:00Z')
        self.db.execute(insert,args)
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute(insert,args)
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute(insert,args[:6]+(-1,)+args[7:])


if __name__ == '__main__':
    unittest.main()
