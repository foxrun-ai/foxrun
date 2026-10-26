"""T474: history actions are explicit, shared, and limited to the reviewed set."""

from __future__ import annotations

import sys as _fox_sys
from pathlib import Path as _FoxPath
_fox_root = next(p for p in _FoxPath(__file__).resolve().parents if (p / 'base/core.py').is_file())
_fox_sys.path[:0] = [str(_fox_root / p) for p in ('base', 'work', 'events', 'decisions', 'memory', 'people', 'design', 'capture')]
_fox_sys.path.insert(0, str(_fox_root))
from base.tests.support import setup as _fox_test_setup
_fox_test_setup()
import ast
from contextlib import closing
import inspect
from pathlib import Path
import sqlite3
import unittest

import work


class HistoryActionTests(unittest.TestCase):
    def test_every_history_call_supplies_an_action(self):
        tree = ast.parse(Path(work.__file__).read_text())
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Name) and n.func.id in ('activity', 'record_activity')]
        self.assertGreater(len(calls), 30)
        for call in calls:
            with self.subTest(line=call.lineno):
                words = [k.value for k in call.keywords if k.arg == 'verb']
                self.assertEqual(len(words), 1, 'Every history call must pass verb explicitly')
                self.assertFalse(isinstance(words[0], ast.Constant) and words[0].value is None)

    def test_action_is_required_even_on_a_legacy_database(self):
        for writer in (work.activity, work.record_activity):
            word = inspect.signature(writer).parameters['verb']
            self.assertEqual(word.default, inspect.Parameter.empty)
            self.assertEqual(word.kind, inspect.Parameter.KEYWORD_ONLY)

    def test_missing_or_invalid_word_never_writes(self):
        with closing(sqlite3.connect(':memory:')) as db:
            db.execute('CREATE TABLE activity (subject_type,subject_id,field,old_value,new_value,actor,source,at,note,verb)')
            for writer, args in ((work.activity, ('T1','comment',None,'1','sol','2026-10-08')),
                                 (work.record_activity, ('function','comms','create',None,'Comms','sol','2026-10-08'))):
                with self.assertRaises(TypeError):
                    writer(db, *args)
                for word in (None, '', 'blocked', 'bounced', 'canceled', 'anything'):
                    with self.subTest(writer=writer.__name__, word=word):
                        with self.assertRaises(work.WorkError):
                            writer(db, *args, verb=word)
            self.assertEqual(db.execute('SELECT count(*) FROM activity').fetchone()[0], 0)

    def test_shared_table_and_unknown_fields(self):
        import history_actions as actions
        self.assertEqual(len(actions.ACTIONS), 33)
        self.assertEqual(len(actions.ACTION_RULES), 111)
        self.assertLessEqual({rule.action for rule in actions.ACTION_RULES.values()} - {None, 'that word'}, actions.ACTIONS)
        cases = [
            ({'field':'create'}, 'created'),
            ({'field':'created'}, 'created'),
            ({'field':'comment'}, 'commented'),
            ({'field':'receipt'}, 'attached'),
            ({'field':'approval', 'new':'approve'}, 'approved'),
            ({'field':'title'}, 'updated'),
            ({'field':'parent'}, 'moved'),
            ({'field':'project'}, 'moved'),
            ({'field':'status', 'new':'done'}, 'finished'),
            ({'field':'status', 'new':'done', 'note':'accepted receipt'}, 'accepted'),
            ({'field':'status', 'new':'in-progress', 'note':'claimed'}, 'claimed'),
            ({'field':'status', 'new':'in-progress'}, 'started'),
            ({'field':'status', 'new':'blocked'}, 'moved'),
            ({'field':'status', 'new':'canceled'}, 'moved'),
            ({'field':'status', 'new':'superseded'}, 'replaced'),
            ({'field':'status', 'new':'ruled', 'subject_type':'decision'}, 'decided'),
            ({'field':'status', 'new':'in-progress', 'command':'bounce'}, 'moved'),
            ({'field':'unreviewed_field'}, None),
            ({'field':'status', 'new':'unreviewed_status'}, None),
            ({'field':'create', 'verb':'unreviewed_verb'}, None),
        ]
        for values, expected in cases:
            with self.subTest(values=values):
                self.assertEqual(actions.history_action(**values), expected)

    def test_both_writers_keep_legacy_schema_and_store_word_when_column_exists(self):
        for has_word in (False, True):
            with self.subTest(has_word=has_word), closing(sqlite3.connect(':memory:')) as db:
                db.execute('CREATE TABLE activity (subject_type,subject_id,field,old_value,new_value,actor,source,at,note'
                           + (',verb)' if has_word else ')'))
                before = db.execute('SELECT sql FROM sqlite_master').fetchall()
                work.activity(db, 'T1', 'comment', None, '1', 'sol', '2026-10-08', verb='created')
                work.record_activity(db, 'function', 'comms', 'create', None, 'Comms', 'sol', '2026-10-08', verb='created')
                self.assertEqual(db.execute('SELECT sql FROM sqlite_master').fetchall(), before)
                self.assertEqual(db.execute('SELECT count(*) FROM activity').fetchone()[0], 2)
                if has_word:
                    self.assertEqual(db.execute('SELECT verb FROM activity').fetchall(), [('created',), ('created',)])


if __name__ == '__main__':
    unittest.main()
