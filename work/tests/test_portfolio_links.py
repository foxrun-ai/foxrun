"""Portfolio aliases stay usable; every link hop stays in the portfolio."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'work/tests'), str(ROOT / 'base')]
import test_work as helpers
from base import paths, tracker, ownership
import work


class PortfolioLinksTests(unittest.TestCase):
    make_db = helpers.WorkWriterTests.make_db
    add_task = helpers.WorkWriterTests.add_task
    call = helpers.WorkWriterTests.call
    rows = helpers.WorkWriterTests.rows
    receipt = helpers.WorkWriterTests.receipt

    def setUp(self):
        helpers.WorkWriterTests.setUp(self)
        self.real_portfolio = paths.portfolio
        self.patch = mock.patch.object(paths, 'portfolio', return_value=self.root)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.alias = self.root / 'workspace-link'
        self.alias.symlink_to(self.receipts.name, target_is_directory=True)
        self.receipt('proof.txt')

    def test_receipt_root_and_nested_link_use_resolved_paths(self):
        (self.receipts / 'proof-link.txt').symlink_to('proof.txt')
        self.assertEqual(0, self.call(self.db, 'claim', 'T1', '--by', 'sol')[0])
        code, output, error = self.call(self.db, 'done', 'T1', '--by', 'sol', '--proof', 'Built',
                                        '--receipt', 'proof-link.txt', receipt_root=self.alias)
        self.assertEqual(0, code, error)
        checked = work.open_receipt(work.existing_path(self.alias, 'receipt root', directory=True), 'proof-link.txt')
        self.addCleanup(checked.close)
        self.assertEqual(self.receipts, checked.root)
        self.assertEqual(self.receipts / 'proof.txt', checked.path)
        row = self.rows(self.db, 'SELECT scope,path FROM task_links')[0]
        self.assertEqual(str(self.receipts), row['scope'])
        self.assertEqual(str(checked.path), row['path'])
        self.assertEqual(self.receipts, paths.workspace(self.alias.name))
        from base.pages_common import safe_path
        self.assertEqual(checked.path, safe_path(self.alias / 'proof-link.txt'))

    def test_link_can_point_to_another_portfolio_workspace(self):
        second = self.root / 'second'
        second.mkdir()
        (second / 'proof.txt').write_text('other workspace proof')
        (self.receipts / 'second').symlink_to(second, target_is_directory=True)
        receipt = work.open_receipt(self.receipts, 'second/proof.txt')
        self.addCleanup(receipt.close)
        self.assertEqual(second / 'proof.txt', receipt.path)
        work.verify_receipt(receipt, self.receipts)

    def test_external_link_and_leave_return_chain_are_refused(self):
        outside = Path(tempfile.mkdtemp(prefix='t634-outside-')).resolve()
        self.addCleanup(__import__('shutil').rmtree, outside)
        (outside / 'back').symlink_to(self.receipts, target_is_directory=True)
        for name, target in [('outside', outside), ('chain', outside / 'back')]:
            alias = self.root / name
            alias.symlink_to(target, target_is_directory=True)
            with self.subTest(name=name):
                code, _, error = self.call(self.db, 'comment', 'T1', 'proof', '--by', 'sol',
                                           receipt_root=alias)
                self.assertEqual(2, code)
                self.assertIn('symlink', error)
                self.assertEqual([], self.rows(self.db, 'SELECT * FROM comments'))

    def test_nested_chain_and_loop_are_refused(self):
        outside = self.root.parent / (self.root.name + '-external')
        outside.mkdir()
        self.addCleanup(outside.rmdir)
        (self.root / 'hop').symlink_to(outside, target_is_directory=True)
        (self.root / 'chain').symlink_to('hop', target_is_directory=True)
        (self.root / 'loop').symlink_to('loop', target_is_directory=True)
        for name in ('chain', 'loop'):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'symlink'):
                paths.resolve_portfolio_path(self.root / name)

    def test_receipt_alias_swap_during_operation_is_refused(self):
        alias = self.receipts / 'linked.txt'
        alias.symlink_to('proof.txt')
        receipt = work.open_receipt(self.receipts, 'linked.txt')
        self.addCleanup(receipt.close)
        (self.receipts / 'other.txt').write_text('different')
        # Replace only a disposable fixture alias.
        changed = self.receipts / 'replacement'
        changed.symlink_to('other.txt')
        os.replace(changed, alias)
        with self.assertRaisesRegex(work.WorkError, 'path changed'):
            work.verify_receipt(receipt, self.receipts)

    def test_relative_evidence_stored_before_rename_still_resolves(self):
        run_code, run_id, error = self.call(self.db, 'run-start', 'T1', '--by', 'sol',
                                            '--model', 'fixture', '--runtime', 'codex')
        self.assertEqual(0, run_code, error)
        self.assertEqual(0, self.call(self.db, 'run-end', run_id.strip(), '--by', 'sol',
                                     '--result', 'pass', '--evidence', 'proof.txt', '--fix-rounds', '0')[0])
        evidence = self.rows(self.db, 'SELECT evidence FROM runs')[0]['evidence']
        old = self.receipts
        new = old.with_name('renamed-workspace')
        old.rename(new)
        old.symlink_to(new.name, target_is_directory=True)
        self.assertEqual(b'evidence', (old / evidence).read_bytes())
        code, _, error = self.call(self.db, 'comment', 'T1', 'after rename', '--by', 'sol',
                                   '--receipt', evidence, receipt_root=old)
        self.assertEqual(0, code, error)

    def test_database_and_relationship_plan_aliases_are_resolved(self):
        import work_relationships
        linked_db = self.root / 'database-link.sqlite'
        linked_db.symlink_to(self.db)
        self.assertEqual(self.db, work.existing_path(linked_db, 'database'))
        self.assertEqual(self.db, work_relationships.existing_database(linked_db))
        planned = work_relationships.write_private_plan(self.alias / 'plan.json', {'fixture': True})
        self.assertEqual(self.receipts / 'plan.json', planned)
        self.assertTrue(planned.is_file())
        self.assertEqual(self.receipts, tracker.local_path(self.root, self.alias.name))

    def test_portfolio_setting_without_environment(self):
        system = self.root / 'system'
        (system / 'config').mkdir(parents=True)
        (system / 'config/person.json').write_text(json.dumps({'portfolio': '..'}))
        with mock.patch.dict(os.environ, {'FOXRUN_HOME': str(system)}):
            with mock.patch.object(paths, 'portfolio', self.real_portfolio):
                with mock.patch.dict(os.environ):
                    os.environ.pop('FOXRUN_PORTFOLIO', None)
                    self.assertEqual(self.receipts, paths.resolve_portfolio_path(self.alias))

    def test_lint_and_approval_use_safe_portfolio_alias(self):
        import approve
        import lint
        import contract_lint
        self.assertEqual(self.receipts, approve.root_path(self.alias))
        checker = object.__new__(lint.Lint)
        checker.workspaces, checker.home = self.root, self.root / 'system'
        checker.cache = {}
        self.assertEqual(self.receipts / 'proof.txt', checker.safe_entry(self.alias, 'proof.txt'))
        self.assertEqual('evidence', checker.page(self.alias / 'proof.txt').lines[0])
        self.assertEqual(self.receipts, contract_lint._roots([self.alias], 'workspace')[0])
