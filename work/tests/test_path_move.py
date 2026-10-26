#!/usr/bin/env python3
"""Synthetic path migration checks. No live tracker writes."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'work'), str(ROOT / 'work/tests')]
from base.tests.support import setup
setup()
import hashlib
import sqlite3
import tempfile
import unittest
from unittest import mock
import test_work as helpers
import work


class PathMoveTests(unittest.TestCase):
    def setUp(self):
        helpers.WorkWriterTests.setUp(self)
        self.add_task_workspace()

    def add_task_workspace(self):
        with sqlite3.connect(self.db) as db:
            db.execute("UPDATE tasks SET tags='workspace:receipts' WHERE id='T1'")
        from base import paths
        patch = mock.patch.object(paths, 'portfolio', return_value=self.root)
        patch.start()
        self.addCleanup(patch.stop)
    make_db = helpers.WorkWriterTests.make_db
    add_task = helpers.WorkWriterTests.add_task
    call = helpers.WorkWriterTests.call
    rows = helpers.WorkWriterTests.rows

    def seed(self, *, spaced=False):
        suffix = 'proof with spaces.md' if spaced else 'proof.md'
        self.old = self.receipts / 'history'
        self.new = self.root / 'hq/history'
        self.new.mkdir(parents=True)
        (self.new / suffix).write_text('synthetic evidence')
        old = str(self.old / suffix)
        with sqlite3.connect(self.db) as db:
            db.execute('ALTER TABLE activity ADD COLUMN verb TEXT')
            db.execute("INSERT INTO runs (id,subject_type,subject_id,\"by\",model,runtime,started_at,evidence) VALUES ('R1','task','T1','sol','fake','codex','now',?)", ('history/' + suffix,))
            db.execute("INSERT INTO task_links(task,system,scope,external_id,path,relation) VALUES ('T1','receipt-root',?,?,?,'produced')", (str(self.receipts), old, old))
            db.execute("INSERT INTO attachments(subject_type,subject_id,path,hash) VALUES ('task','T1',?,'keep-hash')", (old,))
            db.execute("INSERT INTO activity(subject_type,subject_id,field,new_value,actor,at,note) VALUES ('task','T1','receipt',?,'sol','now','kept note')", (old,))
            db.execute("INSERT INTO comments(subject_type,subject_id,author,at,body) VALUES ('task','T1','sol','now',?)", ('Evidence: ' + old + '.',))
        return old

    def move(self, *extra):
        return self.call(self.db, 'path-move', '--from', str(self.old), '--to', str(self.new), *extra)

    def digest(self):
        return hashlib.sha256(self.db.read_bytes()).hexdigest()

    def test_transaction_updates_all_receipt_fields_and_one_audit_per_change(self):
        old = self.seed()
        code, out, err = self.move('--by', 'sol')
        self.assertEqual((0, ''), (code, err))
        self.assertIn('changes=7', out)
        new = str(self.new / 'proof.md')
        self.assertEqual(new, self.rows(self.db, 'SELECT evidence FROM runs')[0]['evidence'])
        self.assertEqual(new, self.rows(self.db, 'SELECT path FROM attachments')[0]['path'])
        self.assertEqual(str(self.new.parent), self.rows(self.db, 'SELECT scope FROM task_links')[0]['scope'])
        self.assertEqual('keep-hash', self.rows(self.db, 'SELECT hash FROM attachments')[0]['hash'])
        self.assertEqual('Evidence: ' + new + '.', self.rows(self.db, 'SELECT body FROM comments')[0]['body'])
        audit = self.rows(self.db, "SELECT * FROM activity WHERE subject_type='path-move'")
        self.assertEqual(7, len(audit))
        self.assertTrue(all(row['verb'] == 'moved' and row['old_value'] for row in audit))
        self.assertEqual(old, next(row['old_value'] for row in audit if row['field'] == 'runs.evidence').replace('history/', str(self.old) + '/', 1))
        self.assertIn('changes=0', self.move('--by', 'sol')[1])
        self.assertEqual(7, len(self.rows(self.db, "SELECT * FROM activity WHERE subject_type='path-move'")))

    def test_dry_run_keeps_database_bytes(self):
        self.seed()
        before = self.digest()
        self.assertEqual(0, self.move('--dry-run')[0])
        self.assertEqual(before, self.digest())

    def test_missing_destination_refuses_every_change_and_dry_run(self):
        self.seed()
        with sqlite3.connect(self.db) as db:
            db.execute("INSERT INTO runs(id,subject_type,subject_id,\"by\",model,runtime,started_at,evidence) VALUES ('R2','task','T1','sol','fake','codex','now','history/missing.md')")
        before = self.digest()
        for flags in [('--dry-run',), ('--by', 'sol')]:
            code, _, err = self.move(*flags)
            self.assertEqual(2, code)
            self.assertIn('destination must already exist', err)
            self.assertEqual(before, self.digest())

    def test_late_database_failure_rolls_back_paths_and_audits(self):
        self.seed()
        with sqlite3.connect(self.db) as db:
            db.execute("CREATE TRIGGER fail_move BEFORE UPDATE ON comments BEGIN SELECT RAISE(ABORT,'synthetic failure'); END")
        before = self.digest()
        self.assertEqual(2, self.move('--by', 'sol')[0])
        self.assertEqual(before, self.digest())

    def test_prefix_boundary_and_unrelated_link_system(self):
        self.seed()
        with sqlite3.connect(self.db) as db:
            db.execute("UPDATE runs SET evidence='history-other/proof.md'")
            db.execute("UPDATE task_links SET system='remote'")
            db.execute("UPDATE comments SET body='Keep /other/history/proof.md and history-other/proof.md'")
        self.assertEqual(0, self.move('--by', 'sol')[0])
        self.assertEqual('history-other/proof.md', self.rows(self.db, 'SELECT evidence FROM runs')[0]['evidence'])
        self.assertIn('/history/proof.md', self.rows(self.db, 'SELECT path FROM task_links')[0]['path'])
        self.assertIn('history-other', self.rows(self.db, 'SELECT body FROM comments')[0]['body'])

    def test_relative_prefix_and_scope_identity(self):
        self.seed()
        code, _, err = self.call(self.db, 'path-move', '--from', '.', '--to', str(self.root / 'hq'), '--by', 'sol')
        self.assertEqual((0, ''), (code, err))
        self.assertEqual(str(self.root / 'hq'), self.rows(self.db, 'SELECT scope FROM task_links')[0]['scope'])

    def test_structured_path_with_spaces(self):
        self.seed(spaced=True)
        with sqlite3.connect(self.db) as db:
            db.execute('UPDATE comments SET body=?', ('Evidence: <' + str(self.old / 'proof with spaces.md') + '>.',))
        self.assertEqual(0, self.move('--by', 'sol')[0])
        self.assertEqual(str(self.new / 'proof with spaces.md'), self.rows(self.db, 'SELECT evidence FROM runs')[0]['evidence'])

    def test_finished_run_retry_works_after_receipt_root_change(self):
        self.seed()
        with sqlite3.connect(self.db) as db:
            db.execute("UPDATE runs SET ended_at='then',result='pass',fix_rounds=0")
        self.assertEqual(0, self.move('--by', 'sol')[0])
        code, out, err = self.call(self.db, 'run-end', 'R1', '--result', 'pass',
                                   '--evidence', 'history/proof.md', '--fix-rounds', '0',
                                   receipt_root=self.new.parent)
        self.assertEqual(0, code, err)
        self.assertIn('duplicate', out)

    def test_general_layout_prose_stays_unchanged(self):
        self.seed()
        body = 'Keep history/outputs/, history/runs, and /other/history/proof.md.'
        with sqlite3.connect(self.db) as db:
            db.execute('UPDATE comments SET body=?', (body,))
        self.assertEqual(0, self.move('--by', 'sol')[0])
        self.assertEqual(body, self.rows(self.db, 'SELECT body FROM comments')[0]['body'])

    def test_structured_traversal_refuses(self):
        self.seed()
        with sqlite3.connect(self.db) as db:
            db.execute("UPDATE runs SET evidence='history/../other.md'")
        self.assertEqual(2, self.move('--dry-run')[0])

    def test_symlink_destination_inside_portfolio_is_accepted(self):
        self.seed()
        (self.new / 'linked.md').symlink_to(self.new / 'proof.md')
        with sqlite3.connect(self.db) as db:
            db.execute("UPDATE runs SET evidence='history/linked.md'")
        self.assertEqual(0, self.move('--dry-run')[0])

    def test_traversal_in_prose_refuses(self):
        self.seed()
        with sqlite3.connect(self.db) as db:
            db.execute("UPDATE comments SET body='Evidence: history/../other.md'")
        self.assertEqual(2, self.move('--dry-run')[0])

    def test_actor_and_flag_scope(self):
        self.seed()
        self.assertEqual(2, self.move()[0])
        self.assertEqual(2, self.call(self.db, 'show', 'T1', '--from', 'history')[0])
        self.assertEqual(2, self.call(self.db, 'path-move', '--from', 'history', '--to', 'history', '--dry-run')[0])

    def test_foreign_workspace_relative_paths_never_rewrite_even_with_collision(self):
        self.seed()
        self.add_task(self.db, 'T2')
        with sqlite3.connect(self.db) as db:
            db.execute("UPDATE tasks SET tags='workspace:other' WHERE id='T2'")
        other = self.root / 'other/history'
        other.mkdir(parents=True)
        (other / 'proof.md').write_text('foreign receipt')
        with sqlite3.connect(self.db) as db:
            db.execute("UPDATE runs SET subject_id='T2'")
            db.execute("UPDATE comments SET subject_id='T2',body='Evidence: history/proof.md'")
            db.execute("UPDATE attachments SET subject_id='T2',path='history/proof.md'")
        self.assertEqual(0, self.move('--by', 'sol')[0])
        self.assertEqual('history/proof.md', self.rows(self.db, 'SELECT evidence FROM runs')[0]['evidence'])
        self.assertEqual('history/proof.md', self.rows(self.db, 'SELECT path FROM attachments')[0]['path'])
        self.assertEqual('Evidence: history/proof.md', self.rows(self.db, 'SELECT body FROM comments')[0]['body'])

    def test_legacy_foreign_collision_refuses_ambiguous_workspace(self):
        self.seed()
        self.add_task(self.db, 'T2')
        folder = self.root / 'other/state'
        folder.mkdir(parents=True)
        (folder / 'proposals.jsonl').write_text('fake foreign data')
        self.old = self.receipts / 'state'
        self.new = self.root / 'hq/state'
        self.new.mkdir()
        (self.new / 'proposals.jsonl').write_text('fake colliding destination')
        second = self.root / 'other-two/state'
        second.mkdir(parents=True)
        (second / 'proposals.jsonl').write_text('second fake foreign receipt')
        with sqlite3.connect(self.db) as db:
            db.execute("UPDATE comments SET subject_id='T2',body='Read state/proposals.jsonl'")
        with mock.patch.object(work._fox_person, 'workspace', return_value='receipts'):
            code, _, err = self.move('--dry-run')
        self.assertEqual(2, code)
        self.assertIn('ambiguous workspace', err)
        self.assertEqual('Read state/proposals.jsonl', self.rows(self.db, 'SELECT body FROM comments')[0]['body'])

    def test_legacy_unique_foreign_file_does_not_use_receipt_root(self):
        self.seed()
        self.add_task(self.db, 'T2')
        folder = self.root / 'other/state'
        folder.mkdir(parents=True)
        (folder / 'proposals.jsonl').write_text('fake foreign data')
        self.old = self.receipts / 'state'
        self.new = self.root / 'hq/state'
        with sqlite3.connect(self.db) as db:
            db.execute("UPDATE comments SET subject_id='T2',body='Read state/proposals.jsonl'")
        with mock.patch.object(work._fox_person, 'workspace', return_value='receipts'):
            self.assertEqual(0, self.move('--dry-run')[0])
        self.assertEqual('Read state/proposals.jsonl', self.rows(self.db, 'SELECT body FROM comments')[0]['body'])

    def test_conflicting_workspace_tags_refuse(self):
        self.seed()
        with sqlite3.connect(self.db) as db:
            db.execute("UPDATE tasks SET tags='workspace:receipts,workspace:other'")
        before = self.digest()
        code, _, err = self.move('--by', 'sol')
        self.assertEqual(2, code)
        self.assertIn('conflicting workspaces', err)
        self.assertEqual(before, self.digest())

    def test_receipt_root_does_not_select_row_workspace(self):
        self.seed()
        (self.root / 'unrelated').mkdir()
        code, out, err = self.call(self.db, 'path-move', '--from', str(self.old), '--to', str(self.new),
                                   '--dry-run', receipt_root=self.root / 'unrelated')
        self.assertEqual(0, code, err)
        self.assertIn('changes=7', out)

    def test_run_subject_comment_inherits_task_workspace(self):
        self.seed()
        self.add_task(self.db, 'T2')
        with sqlite3.connect(self.db) as db:
            db.execute("UPDATE tasks SET tags='workspace:other' WHERE id='T2'")
        with sqlite3.connect(self.db) as db:
            db.execute("UPDATE runs SET subject_id='T2'")
            db.execute("UPDATE comments SET subject_type='run',subject_id='R1',body='Evidence: history/proof.md'")
        self.assertEqual(0, self.move('--dry-run')[0])
        self.assertEqual('Evidence: history/proof.md', self.rows(self.db, 'SELECT body FROM comments')[0]['body'])

    def test_file_prefix_rewrites_relative_prose(self):
        self.seed()
        self.old /= 'proof.md'
        self.new /= 'proof.md'
        with sqlite3.connect(self.db) as db:
            db.execute("UPDATE comments SET body='Evidence: history/proof.md.'")
            db.execute("UPDATE activity SET note='Read history/proof.md'")
        self.assertEqual(0, self.move('--by', 'sol')[0])
        self.assertEqual('Evidence: ' + str(self.new) + '.', self.rows(self.db, 'SELECT body FROM comments')[0]['body'])
        self.assertEqual('Read ' + str(self.new), self.rows(self.db, "SELECT note FROM activity WHERE subject_type='task'")[0]['note'])

    def pre_move(self):
        self.seed()
        self.old.mkdir()
        (self.new / 'proof.md').rename(self.old / 'proof.md')
        temporary = tempfile.TemporaryDirectory(prefix='path-plan-')
        self.addCleanup(temporary.cleanup)
        self.plan_file = Path(temporary.name).resolve() / 'path-plan.json'

    def test_pre_move_plan_accepts_sources_and_keeps_database_bytes(self):
        self.pre_move()
        before = self.digest()
        self.assertEqual(0, self.move('--plan-out', str(self.plan_file))[0])
        self.assertEqual(before, self.digest())
        self.assertTrue(self.plan_file.is_file())
        (self.old / 'proof.md').rename(self.new / 'proof.md')
        self.assertEqual(0, self.call(self.db, 'path-move', '--plan', str(self.plan_file), '--by', 'sol')[0])
        self.assertEqual(str(self.new / 'proof.md'), self.rows(self.db, 'SELECT evidence FROM runs')[0]['evidence'])

    def test_legacy_saved_plan_keeps_ownership_after_the_source_moves(self):
        self.pre_move()
        foreign = self.root / 'other/history'
        foreign.mkdir(parents=True)
        (foreign / 'proof.md').write_text('fake foreign receipt with the same name')
        with sqlite3.connect(self.db) as db:
            db.execute("UPDATE tasks SET tags=NULL WHERE id='T1'")
        with mock.patch.object(work._fox_person, 'workspace', return_value='receipts'):
            self.assertEqual(0, self.move('--plan-out', str(self.plan_file))[0])
            (self.old / 'proof.md').rename(self.new / 'proof.md')
            code, _, err = self.call(self.db, 'path-move', '--plan', str(self.plan_file), '--by', 'sol')
        self.assertEqual(0, code, err)

    def test_pre_move_plan_refuses_missing_source_and_destination(self):
        self.seed()
        with sqlite3.connect(self.db) as db:
            db.execute("UPDATE runs SET evidence='history/absent.md'")
        plan = self.root / 'absent-plan.json'
        before = self.digest()
        code, out, err = self.move('--plan-out', str(plan))
        self.assertEqual(2, code)
        self.assertIn('source or destination must exist', err)
        self.assertEqual('', out)
        self.assertFalse(plan.exists())
        self.assertEqual(before, self.digest())

    def test_saved_plan_refuses_changed_rows_and_new_matches(self):
        for mutation in ["UPDATE comments SET body='Changed history/proof.md'",
                         "INSERT INTO comments(subject_type,subject_id,author,at,body) VALUES ('task','T1','sol','now','New history/proof.md')",
                         "UPDATE tasks SET tags='workspace:other' WHERE id='T1'",
                         "UPDATE attachments SET hash='changed'"]:
            with self.subTest(mutation=mutation):
                self.pre_move()
                self.assertEqual(0, self.move('--plan-out', str(self.plan_file))[0])
                (self.old / 'proof.md').rename(self.new / 'proof.md')
                with sqlite3.connect(self.db) as db:
                    db.execute(mutation)
                before = self.digest()
                code, out, err = self.call(self.db, 'path-move', '--plan', str(self.plan_file), '--by', 'sol')
                self.assertEqual(2, code)
                self.assertIn('plan is stale', err)
                self.assertEqual('', out)
                self.assertEqual(before, self.digest())
                # Each subtest gets an independent fixture, without deleting payloads.
                self.setUp()

    def test_saved_plan_refuses_wrong_database_and_missing_destination(self):
        self.pre_move()
        self.assertEqual(0, self.move('--plan-out', str(self.plan_file))[0])
        before = self.digest()
        code, out, err = self.call(self.db, 'path-move', '--plan', str(self.plan_file), '--by', 'sol')
        self.assertEqual(2, code)
        self.assertIn('destination must already exist', err)
        self.assertEqual('', out)
        self.assertEqual(before, self.digest())
        second = self.make_db('two.sqlite')
        code, _, err = self.call(second, 'path-move', '--plan', str(self.plan_file), '--by', 'sol')
        self.assertEqual(2, code)
        self.assertIn('another database', err)

    def test_write_refreshes_state_but_planning_does_not(self):
        self.seed()
        with mock.patch.object(work, 'export_after_write') as export:
            self.assertEqual(0, self.move('--dry-run')[0])
            export.assert_not_called()
            self.assertEqual(0, self.move('--by', 'sol')[0])
            export.assert_called_once()


if __name__ == '__main__':
    unittest.main()
