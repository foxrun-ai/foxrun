"""Version-three readers preserve ownership and hold unsupported mutations."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

import test_dayone_release as fixture


class SnapshotCompatibility(unittest.TestCase):
    def setUp(self):
        fixture.PROOF = Path(tempfile.mkdtemp(prefix='snapshot-reader-')).resolve()
        fixture.HOME = fixture.PROOF / 'fake-home'
        fixture.REPO = fixture.HOME / '.foxrun/skillwright'
        fixture.SHELF = fixture.HOME / '.foxrun/skills'
        self.env, self.overrides = fixture.setup()
        self.repo = fixture.REPO
        self.shelf = fixture.SHELF
        self.assertTrue((self.repo / 'config/catalog.yaml').is_symlink())
        self.assertEqual(os.readlink(self.repo / 'config/catalog.yaml'), '../../config/catalog.yaml')
        self.route = self.repo / 'tools/skill_route.py'
        self.ship = self.repo / 'tools/skill_ship.py'

    def run_cli(self, tool, *args, ok=True):
        return fixture.run(sys.executable, '-B', tool, *args, env=self.env, ok=ok)

    def metadata(self):
        paths = [self.shelf / '.release-manifest.json', self.repo / 'manifests/shipped.yaml',
                 Path(self.env['SKILLS_PIN_PATH']), self.repo / 'skill-state/release-state.json']
        return [p.read_bytes() for p in paths]

    def test_git_rebuild_proves_exact_release_and_rejects_drift(self):
        record = json.loads((self.shelf / '.release-manifest.json').read_text())
        candidate = self.repo / 'skill-releases' / record['release_id']
        candidate.parent.mkdir()
        shutil.copytree(self.shelf, candidate, symlinks=True)
        script = 'import skill_ship; from pathlib import Path; skill_ship.prove_git_rebuild(Path(__import__("sys").argv[1]))'
        fixture.run(sys.executable, '-B', '-c', script, candidate,
                    cwd=self.repo / 'tools', env=self.env)
        page = candidate / 'close/SKILL.md'
        page.chmod(0o644)
        page.write_text(page.read_text() + '\nchanged\n')
        failed = fixture.run(sys.executable, '-B', '-c', script, candidate,
                             cwd=self.repo / 'tools', env=self.env, ok=False)
        self.assertNotEqual(failed.returncode, 0)
        self.assertTrue(candidate.is_dir())

    def test_parity_dry_run_individual_links(self):
        before = self.metadata()
        result = self.run_cli(self.route, 'dry-run', '--candidate', self.shelf)
        report = json.loads(result.stdout)
        self.assertEqual(report['actions'], {'keep_link': 5})
        self.assertEqual(report['blocked'], [])
        self.assertEqual(self.metadata(), before)

    def test_parity_dry_run_root_link(self):
        root = Path(self.env['SKILLS_CLAUDE_ROOT'])
        for name in fixture.NAMES:
            (root / name).unlink()
        root.rmdir(); root.symlink_to(self.shelf)
        report = json.loads(self.run_cli(self.route, 'dry-run', '--candidate', self.shelf).stdout)
        self.assertEqual(report['actions'], {'keep_link': 5})
        self.assertEqual(report['blocked'], [])

    def test_parity_dry_run_preserves_physical_and_approval_decision(self):
        root = Path(self.env['SKILLS_CLAUDE_ROOT'])
        (root / 'close').unlink(); (root / 'close').mkdir()
        page = root / 'close/SKILL.md'; page.write_text('Owner variant.\n')
        policy_path = self.repo / 'config/catalog.yaml'
        policy = json.loads(policy_path.read_text())
        policy['claude_approval_required']['close'] = dict(action='convert_to_shared_link', reason='Reviewed owner decision.')
        policy_path.write_text(json.dumps(policy))
        policy_before = policy_path.read_bytes()
        report = json.loads(self.run_cli(self.route, 'dry-run', '--candidate', self.shelf).stdout)
        self.assertEqual(report['changes'], [])
        self.assertEqual(report['blocked'][0]['name'], 'close')
        self.assertEqual(page.read_text(), 'Owner variant.\n')
        self.assertEqual(policy_path.read_bytes(), policy_before)

    def test_prepare_holds_before_mutation(self):
        before = self.metadata(); output = fixture.PROOF / 'parity-sandbox'
        result = self.run_cli(self.route, 'prepare', '--candidate', self.shelf, '--output', output, ok=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('no reviewed Claude ownership baseline', result.stderr)
        self.assertFalse(output.exists())
        self.assertEqual(self.metadata(), before)

    def test_apply_holds_before_mutation(self):
        before = self.metadata(); archive = fixture.PROOF / 'parity-archive'
        result = self.run_cli(self.route, 'apply', '--candidate', self.shelf, '--archive', archive, ok=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('no reviewed Claude ownership baseline', result.stderr)
        self.assertFalse(archive.exists())
        self.assertFalse((self.repo / 'skill-state/lifecycle.lock').exists())
        self.assertEqual(self.metadata(), before)

    def test_validation_accepts_snapshot_and_rejects_corrupt_record(self):
        self.run_cli(self.ship, 'validate', '--candidate', self.shelf)
        path = self.shelf / '.release-manifest.json'
        record = json.loads(path.read_text()); record['digest'] = '0' * 64
        path.chmod(0o644); path.write_text(json.dumps(record))
        result = self.run_cli(self.ship, 'validate', '--candidate', self.shelf, ok=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('release record is invalid', result.stderr)

    def test_validation_rejects_stale_source(self):
        path = self.repo / 'skills/close/SKILL.md'
        path.write_text(path.read_text() + 'Changed.\n')
        fixture.run('git', '-C', self.repo, 'add', '.', env=self.env)
        fixture.run('git', '-C', self.repo, 'commit', '-q', '-m', 'Change source', env=self.env)
        result = self.run_cli(self.ship, 'validate', '--candidate', self.shelf, ok=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('distribution source digest is stale: close', result.stderr)

    def test_readiness_reports_valid_snapshot_and_explicit_hold(self):
        before = self.metadata()
        result = self.run_cli(self.ship, 'readiness', ok=False)
        report = json.loads(result.stdout)
        self.assertEqual(result.returncode, 1)
        self.assertTrue(report['active_valid'])
        self.assertFalse(report['ready_to_build'])
        self.assertIn('full_publication', [item['check'] for item in report['blockers']])
        self.assertNotIn('distribution', [item['check'] for item in report['blockers']])
        self.assertEqual(self.metadata(), before)

    def test_full_build_and_publish_hold_before_mutation(self):
        before = self.metadata()
        for args in [('build',), ('publish', '--candidate', self.shelf, '--authorize-reviewed', 'snapshot')]:
            result = self.run_cli(self.ship, *args, ok=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('on hold', result.stderr)
        self.assertFalse((self.repo / 'skill-state/lifecycle.lock').exists())
        self.assertFalse((self.repo / 'skill-releases').exists())
        self.assertEqual(self.metadata(), before)

    def test_preview_flag_does_not_relax_actual_ship(self):
        shutil.rmtree(self.repo / 'skills/close/replays')
        fixture.run('git', '-C', self.repo, 'add', '.', env=self.env)
        fixture.run('git', '-C', self.repo, 'commit', '-q', '-m', 'Remove replay', env=self.env)
        fixture.run('git', '-C', self.repo, 'push', '-q', 'origin', 'main', env=self.env)
        before = self.metadata()
        self.env['SKILLIFY_PREVIEW_CHANGED'] = '0'
        result = self.run_cli(self.ship, 'ship', '--skill', 'close', *self.overrides, ok=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('check 8 replay cases', result.stderr)
        self.assertFalse(self.shelf.is_symlink())
        self.assertEqual(self.metadata(), before)

    def test_wrong_root_link_refuses_and_preserves_ownership(self):
        root = Path(self.env['SKILLS_CLAUDE_ROOT'])
        for name in fixture.NAMES:
            (root / name).unlink()
        root.rmdir()
        foreign = fixture.PROOF / 'owner-root'; foreign.mkdir()
        (foreign / 'close').mkdir()
        page = foreign / 'close/SKILL.md'; page.write_text('Owner variant.\n')
        root.symlink_to(foreign)
        path = self.repo / 'skills/close/SKILL.md'
        path.write_text(path.read_text().replace('Run the fx-close skill.', 'Use the fx-close skill.'))
        fixture.run('git', '-C', self.repo, 'add', '.', env=self.env)
        fixture.run('git', '-C', self.repo, 'commit', '-q', '-m', 'Change checked skill', env=self.env)
        fixture.run('git', '-C', self.repo, 'push', '-q', 'origin', 'main', env=self.env)
        before = self.metadata()
        result = self.run_cli(self.ship, 'ship', '--skill', 'close', *self.overrides, ok=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('no stable shelf link', result.stderr)
        self.assertFalse(self.shelf.is_symlink())
        self.assertFalse((self.repo / 'skill-releases').exists())
        self.assertEqual(self.metadata(), before)
        self.assertEqual(root.resolve(), foreign)
        self.assertEqual(page.read_text(), 'Owner variant.\n')


if __name__ == '__main__':
    unittest.main()
