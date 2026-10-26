"""Recorded task approval permits sign-off by the acting seat."""

from __future__ import annotations

import sys as _fox_sys
from pathlib import Path as _FoxPath
_fox_root = next(p for p in _FoxPath(__file__).resolve().parents if (p / 'base/core.py').is_file())
_fox_sys.path[:0] = [str(_fox_root / p) for p in ('base', 'work', 'events', 'decisions', 'memory', 'people', 'design', 'capture')]
_fox_sys.path.insert(0, str(_fox_root))
from base.tests.support import setup as _fox_test_setup
_fox_test_setup()

from contextlib import closing
import sqlite3
import unittest

from night_work_fixtures import WriterCase


class AcceptApprovalTests(WriterCase):
    def setUp(self):
        super().setUp()
        (self.root / 'proof.md').write_text('Synthetic review proof\n')
        self.finish()

    def finish(self):
        self.sql("UPDATE tasks SET owner='architect',claimed_by='architect' WHERE id='T1'")
        self.assert_ok(self.call('done', 'T1', '--by', 'architect', '--proof', 'proof.md', '--note', 'Checked'))

    def approval(self, *, subject_type='task', subject_id='T1', call='approve', words='Okay, that works'):
        self.sql("INSERT INTO approvals(id,subject_type,subject_id,call,person_words,given_at) "
                 "VALUES (1,?,?,?,?, '2026-10-16')", (subject_type, subject_id, call, words))

    def assert_accepted(self, actor, *, status='done', note='accepted'):
        before = len(self.sql('SELECT * FROM activity'))
        self.assert_ok(self.call('accept', 'T1', '--by', actor, '--approval', '1'))
        self.assertEqual([(status,)], self.sql("SELECT status FROM tasks WHERE id='T1'"))
        self.assertEqual(before + 1, len(self.sql('SELECT * FROM activity')))
        self.assertEqual([(actor, note + '; approval=1')], self.sql(
            "SELECT actor,note FROM activity WHERE subject_type='task' AND subject_id='T1' "
            "AND field='status' ORDER BY id DESC LIMIT 1"))
        if status == 'done':
            self.assertEqual([('accepted',)], self.sql("SELECT verb FROM activity WHERE field='status' ORDER BY id DESC LIMIT 1"))
        before_retry = self.db.read_bytes()
        self.assertIn('duplicate', self.call('accept', 'T1', '--by', actor, '--approval', '1')[1])
        self.assertEqual(before_retry, self.db.read_bytes())

    def test_accept_with_approval_by_non_lead(self):
        self.approval()
        self.assert_accepted('observer')

    def test_accept_with_approval_by_finisher(self):
        self.approval()
        self.assert_accepted('architect')

    def test_accept_with_approval_has_no_named_lead_requirement(self):
        self.approval()
        self.assert_accepted('lead')

    def test_accept_refuses_approval_for_another_task(self):
        self.approval(subject_id='T2')
        result = self.assert_refused_without_write('accept', 'T1', '--by', 'observer', '--approval', '1')
        self.assertIn('--approval 1 is for T2; expected T1', result[2])

    def test_accept_refuses_other_calls(self):
        self.approval()
        for call in ('discuss', 'wrong', 'edit'):
            with self.subTest(call=call):
                self.sql('UPDATE approvals SET call=?', (call,))
                result = self.assert_refused_without_write('accept', 'T1', '--by', 'observer', '--approval', '1')
                self.assertIn(f'--approval 1 has call={call}; expected approve', result[2])

    def test_accept_refuses_empty_words(self):
        self.approval()
        for words in (None, '', ' \t\n '):
            with self.subTest(words=words):
                self.sql('UPDATE approvals SET person_words=?', (words,))
                result = self.assert_refused_without_write('accept', 'T1', '--by', 'observer', '--approval', '1')
                self.assertIn('--approval 1 needs non-empty person_words', result[2])

    def test_accept_refuses_wrong_subject_type(self):
        self.approval(subject_type='decision')
        result = self.assert_refused_without_write('accept', 'T1', '--by', 'observer', '--approval', '1')
        self.assertIn('--approval 1 has subject_type=decision; expected task', result[2])

    def test_accept_refuses_missing_approval(self):
        for reference, message in (('999', 'must name an approvals row'),
                                   ('not-an-id', 'must name an approvals row'),
                                   ('', '--approval must be one non-empty line')):
            with self.subTest(reference=reference):
                result = self.assert_refused_without_write('accept', 'T1', '--by', 'observer', '--approval', reference)
                self.assertIn(message, result[2])

    def test_accept_without_approval_keeps_signer_rules(self):
        self.approval()
        # g-close-on-evidence-not-seat (2026-10-17): keep the finisher rule; remove the seat rule.
        result = self.assert_refused_without_write('accept', 'T1', '--by', 'architect')
        self.assertIn('finisher rule', result[2])
        self.assert_ok(self.call('accept', 'T1', '--by', 'observer'))
        self.assertEqual([('done',)], self.sql("SELECT status FROM tasks WHERE id='T1'"))

    def test_accept_with_approval_keeps_review_and_receipt_rules(self):
        # g-close-on-evidence-not-seat (2026-10-17): neither receipt nor proof means no evidence.
        self.approval()
        self.sql("UPDATE tasks SET status='todo' WHERE id='T1'")
        result = self.assert_refused_without_write('accept', 'T1', '--by', 'observer', '--approval', '1')
        self.assertIn('task must be in-review before sign-off', result[2])
        self.sql("UPDATE tasks SET status='in-review' WHERE id='T1'")
        self.sql("DELETE FROM activity WHERE field='receipt'")
        self.sql("DELETE FROM attachments WHERE subject_type='task' AND subject_id='T1'")
        self.sql("DELETE FROM comments WHERE substr(body,1,6)='Proof:'")
        result = self.assert_refused_without_write('accept', 'T1', '--by', 'observer', '--approval', '1')
        self.assertIn('task has no receipt', result[2])

    def test_non_lead_accepts_receipt_without_proof_attachment(self):
        self.sql("DELETE FROM comments WHERE substr(body,1,6)='Proof:'")
        self.sql("DELETE FROM attachments WHERE subject_type='task' AND subject_id='T1'")
        self.assert_ok(self.call('accept', 'T1', '--by', 'chief-of-staff'))
        self.assertEqual([('done',)], self.sql("SELECT status FROM tasks WHERE id='T1'"))

    def test_non_lead_accepts_proof_without_receipt(self):
        # g-close-on-evidence-not-seat (2026-10-17): an attached proof also satisfies evidence.
        self.sql("DELETE FROM activity WHERE field='receipt'")
        self.assert_ok(self.call('accept', 'T1', '--by', 'observer'))
        self.assertEqual([('done',)], self.sql("SELECT status FROM tasks WHERE id='T1'"))

    def test_no_evidence_or_blank_evidence_refuses_without_writes(self):
        for blank in ('', ' ', '\t\n\r\f\v', '\u00a0', '\u2003'):
            with self.subTest(blank=repr(blank)):
                self.sql("UPDATE activity SET new_value=? WHERE field='receipt'", (blank,))
                self.sql("UPDATE comments SET body=? WHERE substr(body,1,6)='Proof:'", ('Proof: ' + blank,))
                self.sql("UPDATE attachments SET path=?,hash=? WHERE subject_type='task' AND subject_id='T1'", (blank, blank))
                result = self.assert_refused_without_write('accept', 'T1', '--by', 'observer')
                self.assertIn('no receipt or proof', result[2])

    def test_plain_proof_comment_is_not_attached_evidence(self):
        self.sql("DELETE FROM activity WHERE field='receipt'")
        self.sql("DELETE FROM attachments WHERE subject_type='task' AND subject_id='T1'")
        self.assert_ok(self.call('comment', 'T1', 'Proof: I checked it', '--by', 'observer'))
        result = self.assert_refused_without_write('accept', 'T1', '--by', 'observer')
        self.assertIn('no receipt or proof', result[2])

    def test_proof_attachment_needs_path_and_hash(self):
        self.sql("DELETE FROM activity WHERE field='receipt'")
        for field in ('path', 'hash'):
            with self.subTest(field=field):
                original = self.sql(f"SELECT {field} FROM attachments")[0][0]
                self.sql(f"UPDATE attachments SET {field}=' '")
                result = self.assert_refused_without_write('accept', 'T1', '--by', 'observer')
                self.assertIn('no receipt or proof', result[2])
                self.sql(f"UPDATE attachments SET {field}=?", (original,))

    def test_non_lead_owner_and_claimant_cannot_sign(self):
        for field in ('owner', 'claimed_by'):
            with self.subTest(field=field):
                self.sql(f"UPDATE tasks SET {field}='observer' WHERE id='T1'")
                result = self.assert_refused_without_write('accept', 'T1', '--by', 'observer')
                self.assertIn(field + ' rule', result[2])
                self.sql(f"UPDATE tasks SET {field}='architect' WHERE id='T1'")

    def test_person_checker_cannot_sign_a_migrated_own_finish(self):
        # T649: every signer stays subject to the finisher rule unless --approval records the person's yes.
        self.sql("UPDATE tasks SET check_by='person' WHERE id='T1'")
        self.sql("DELETE FROM activity WHERE field='status' AND verb='finished'")
        for source in ('receipt', 'Proof: comment'):
            with self.subTest(source=source):
                self.sql("UPDATE activity SET actor=? WHERE field='receipt'", ('person' if source == 'receipt' else 'architect',))
                self.sql("UPDATE comments SET author=? WHERE substr(body,1,6)='Proof:'", ('person' if source == 'Proof: comment' else 'architect',))
                result = self.assert_refused_without_write('accept', 'T1', '--by', 'person')
                self.assertIn('finisher rule', result[2])
        self.approval()
        self.assert_accepted('person')

    def test_person_checker_can_sign_someone_elses_work(self):
        self.sql("UPDATE tasks SET check_by='person' WHERE id='T1'")
        result = self.assert_refused_without_write('accept', 'T1', '--by', 'observer')
        self.assertIn('must sign off this task', result[2])
        self.assert_ok(self.call('accept', 'T1', '--by', 'person'))

    def test_person_owned_task_requires_evidence_even_with_approval(self):
        # g-close-on-evidence-not-seat (2026-10-17): attached evidence is required before every accept.
        self.approval()
        self.sql("UPDATE tasks SET owner='person' WHERE id='T1'")
        self.sql("DELETE FROM activity WHERE field='receipt'")
        self.sql("DELETE FROM attachments WHERE subject_type='task' AND subject_id='T1'")
        self.sql("DELETE FROM comments WHERE substr(body,1,6)='Proof:'")
        result = self.assert_refused_without_write('accept', 'T1', '--by', 'person', '--approval', '1')
        self.assertIn('no receipt or proof', result[2])

    def test_person_owner_or_claimant_requires_recorded_approval(self):
        # T649: the signer cannot be owner or claimant; --approval keeps the person's own yes.
        self.approval()
        for field in ('owner', 'claimed_by'):
            with self.subTest(field=field):
                self.sql(f"UPDATE tasks SET {field}='person' WHERE id='T1'")
                result = self.assert_refused_without_write('accept', 'T1', '--by', 'person')
                self.assertIn(field + ' rule', result[2])
                self.sql(f"UPDATE tasks SET {field}='architect' WHERE id='T1'")
        self.sql("UPDATE tasks SET owner='person',claimed_by='person' WHERE id='T1'")
        self.assert_accepted('person')

    def test_legacy_non_lead_needs_evidence_and_cannot_be_finisher(self):
        # g-close-on-evidence-not-seat (2026-10-17): proof attachments replace the receipt-only restriction.
        self.db = self.root / 'legacy.sqlite'
        with closing(sqlite3.connect(self.db)) as db:
            db.executescript((_fox_root / 'work/fixtures/pre_t309.sql').read_text())
            db.execute("INSERT INTO tasks(id,title,flag) VALUES ('T1','Legacy task',1)")
            db.commit()
        self.finish()
        self.sql("DELETE FROM activity WHERE field='receipt'")
        result = self.assert_refused_without_write('accept', 'T1', '--by', 'architect')
        self.assertIn('finisher rule', result[2])
        self.sql("DELETE FROM comments WHERE substr(body,1,6)='Proof:'")
        self.sql("DELETE FROM attachments WHERE subject_type='task' AND subject_id='T1'")
        result = self.assert_refused_without_write('accept', 'T1', '--by', 'observer')
        self.assertIn('no receipt or proof', result[2])
        self.finish()
        self.sql("DELETE FROM activity WHERE field='receipt'")
        self.assert_ok(self.call('accept', 'T1', '--by', 'observer'))
        self.assertEqual([('accepted',)], self.sql("SELECT status FROM tasks WHERE id='T1'"))

    def test_accept_with_approval_on_legacy_tracker(self):
        self.db = self.root / 'legacy.sqlite'
        with closing(sqlite3.connect(self.db)) as db:
            db.executescript((_fox_root / 'work/fixtures/pre_t309.sql').read_text())
            db.execute("INSERT INTO tasks(id,title,flag) VALUES ('T1','Legacy task',1)")
            db.commit()
        self.finish()
        self.approval()
        self.assert_accepted('architect', status='accepted', note='accepted receipt')


if __name__ == '__main__':
    unittest.main()
