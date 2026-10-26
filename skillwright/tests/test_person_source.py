"""The person's own skill source ships beside the product skills; each release records its owner (T675)."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import test_dayone_release as fixture


class PersonSource(unittest.TestCase):
    def setUp(self):
        fixture.PROOF = Path(tempfile.mkdtemp(prefix='person-source-')).resolve()
        fixture.HOME = fixture.PROOF / 'fake-home'
        fixture.REPO = fixture.HOME / '.foxrun/skillwright'
        fixture.SHELF = fixture.HOME / '.foxrun/skills'
        env, self.overrides = fixture.setup()
        self.repo, self.shelf = fixture.REPO, fixture.SHELF
        self.ship = self.repo / 'tools/skill_ship.py'
        # The person's repository holds their own copy of close, under the same name as the product's.
        self.person = fixture.PROOF / 'person'
        (self.person / 'skills').mkdir(parents=True)
        shutil.copytree(self.repo / 'skills/close', self.person / 'skills/close')
        self.page = self.person / 'skills/close/SKILL.md'
        self.page.write_text(self.page.read_text().replace('Run the fx-close skill.', 'Use the fx-close skill.'))
        self.git('init', '-q', '-b', 'main', self.person)
        self.git('-C', self.person, 'config', 'user.name', 'Person source proof')
        self.git('-C', self.person, 'config', 'user.email', 'proof@local')
        origin = fixture.PROOF / 'person.git'
        self.git('init', '-q', '--bare', origin)
        self.git('-C', self.person, 'remote', 'add', 'origin', origin)
        self.env = dict(env, SKILLS_PERSON_ROOT=str(self.person))
        self.product_page = (self.repo / 'skills/close/SKILL.md').read_bytes()

    def git(self, *args):
        return fixture.run('git', *args)

    def commit(self, message):
        self.git('-C', self.person, 'add', '-A')
        self.git('-C', self.person, 'commit', '-q', '-m', message)
        self.git('-C', self.person, 'push', '-q', '-u', 'origin', 'main')

    def cli(self, *args, ok=True):
        return fixture.run(sys.executable, '-B', self.ship, *args, env=self.env, ok=ok)

    def record(self):
        return json.loads((self.shelf / '.release-manifest.json').read_text())

    def test_clipy_canonical_guide_needs_no_reference_rewrite(self):
        page = self.person / 'skills/clipy/SKILL.md'
        page.parent.mkdir(parents=True)
        page.write_text('Human guide: `~/.foxrun/tools/mcp/clipy.md`.\n')
        sys.path.insert(0, str(self.repo / 'tools'))
        from skill_scoped import reference_rewrites
        self.assertEqual({}, reference_rewrites(page.parent, self.person))

    def test_person_copy_ships_with_owner_and_product_never_replaces_it(self):
        checked = fixture.run(sys.executable, '-B', self.repo / 'skills/skillify/bin/skillify', 'check', 'close', env=self.env)
        self.assertIn('ready close', checked.stdout)
        self.commit('Person copy of close')
        shipped = self.cli('ship', '--skill', 'close', *self.overrides)
        self.assertIn('shipped close', shipped.stdout)
        self.assertEqual(self.page.read_bytes(), (self.shelf / 'close/SKILL.md').read_bytes())
        self.assertEqual(self.product_page, (self.repo / 'skills/close/SKILL.md').read_bytes())
        record = self.record()
        self.assertEqual(record['skills']['close']['owner'], 'person')
        for name in fixture.NAMES:
            if name != 'close':
                self.assertEqual(record['skills'][name]['owner'], 'product', name)
        self.assertEqual(record, json.loads((self.repo / 'manifests/shipped.yaml').read_text()))
        self.assertIn('no-op:', self.cli('ship', '--skill', 'close', *self.overrides).stdout)
        # With the person's copy gone, the product copy would replace a person-owned skill: refuse.
        self.git('-C', self.person, 'rm', '-q', '-r', 'skills/close')
        (self.person / 'skills/keep').mkdir(parents=True)
        (self.person / 'skills/keep/SKILL.md').write_text('---\nname: keep\ndescription: Keeps the folder.\n---\n')
        self.commit('Person removes close')
        before = (self.shelf / 'close/SKILL.md').read_bytes()
        refused = self.cli('ship', '--skill', 'close', *self.overrides, ok=False)
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("person's", refused.stderr)
        self.assertEqual(before, (self.shelf / 'close/SKILL.md').read_bytes())

    def prepare_retirement(self):
        # A person-only skill, plus a person override of a product skill.
        skill = self.person / 'skills/swipe-review'
        shutil.copytree(self.person / 'skills/close', skill)
        (skill / 'SKILL.md').write_text(self.page.read_text().replace('name: close', 'name: swipe-review'))
        self.commit('Person adds swipe-review')
        canary = fixture.PROOF / 'retirement-canary.py'
        canary.write_text('import os\nfrom pathlib import Path\n'
                          'shelf=Path(os.environ["SKILLS_ACTIVE_PATH"])\n'
                          'for page in shelf.glob("*/SKILL.md"): print(page.parent.name + ": present")\n')
        self.overrides = [item for runtime in ('claude', 'codex', 'hermes')
                          for item in ('--canary-command', runtime + '=' + sys.executable + ' -B ' + str(canary))]
        self.cli('ship', '--skill', 'swipe-review', *self.overrides)
        self.cli('ship', '--skill', 'close', *self.overrides)
        self.assertEqual(self.record()['skills']['swipe-review']['owner'], 'person')
        (self.person / 'retired').mkdir()
        skill.rename(self.person / 'retired/swipe-review')
        self.commit('Person retires swipe-review')

    def test_next_unchanged_ship_removes_retired_person_skill_and_keeps_product(self):
        self.prepare_retirement()
        before = self.record()
        shipped = self.cli('ship', '--skill', 'close', *self.overrides)
        self.assertIn('shipped close', shipped.stdout)
        record = self.record()
        self.assertFalse((self.shelf / 'swipe-review').exists())
        self.assertEqual(record['removed'], ['swipe-review'])
        self.assertNotIn('swipe-review', record['skills'])
        for name, entry in before['skills'].items():
            if name != 'swipe-review':
                self.assertEqual(record['skills'][name], entry, name)
        self.assertEqual(record, json.loads((self.repo / 'manifests/shipped.yaml').read_text()))
        receipt = json.loads((self.repo / 'skill-state/ships' / (record['release_id'] + '.json')).read_text())
        self.assertEqual(receipt['removed'], ['swipe-review'])
        self.assertIn('no-op:', self.cli('ship', '--skill', 'close', *self.overrides).stdout)
        self.page.write_text(self.page.read_text() + '\nAnother checked change.\n')
        self.commit('Person edits close after retirement')
        self.cli('ship', '--skill', 'close', *self.overrides)
        self.assertEqual(self.record()['removed'], ['swipe-review'])
        self.assertIn('no-op:', self.cli('ship', '--skill', 'swipe-review', *self.overrides).stdout)

    def test_retirement_only_ship_dry_run_and_rollback(self):
        self.prepare_retirement()
        before = self.record()
        preview = self.cli('ship', '--skill', 'swipe-review', '--dry-run')
        self.assertIn('dry-run:', preview.stdout)
        self.assertEqual(self.record(), before)
        self.cli('ship', '--skill', 'swipe-review', *self.overrides)
        record = self.record()
        self.assertEqual(record['removed'], ['swipe-review'])
        self.assertFalse((self.shelf / 'swipe-review').exists())
        self.assertIn('no-op:', self.cli('ship', '--skill', 'swipe-review', *self.overrides).stdout)
        self.cli('rollback', '--authorize-reviewed', record['release_id'])
        self.assertEqual(self.record(), before)
        self.assertTrue((self.shelf / 'swipe-review/SKILL.md').is_file())

    def test_retirement_failure_restores_shelf_and_records(self):
        self.prepare_retirement()
        before = self.record()
        failure = fixture.PROOF / 'failed-retirement-canary.py'
        failure.write_text('raise SystemExit(1)\n')
        overrides = [item for runtime in ('claude', 'codex', 'hermes')
                     for item in ('--canary-command', runtime + '=' + sys.executable + ' -B ' + str(failure))]
        refused = self.cli('ship', '--skill', 'swipe-review', *overrides, ok=False)
        self.assertNotEqual(refused.returncode, 0)
        self.assertEqual(self.record(), before)
        self.assertEqual(before, json.loads((self.repo / 'manifests/shipped.yaml').read_text()))
        self.assertTrue((self.shelf / 'swipe-review/SKILL.md').is_file())

    def test_removal_requires_person_ownership_and_no_product_source(self):
        self.prepare_retirement()
        # Unknown and product-owned snapshots remain even when no source holds them.
        record = self.record()
        record['skills']['missing-product'] = dict(owner='product')
        record['skills']['never-person-owned'] = {}
        record['skills']['close']['owner'] = 'person'
        self.page.rename(self.person / 'retired/close.md')
        self.commit('Person removes override; product source remains')
        script = ('import json,sys; import skill_ship as tool; '
                  'print(json.dumps(tool.removed_person_skills(json.loads(sys.argv[1]))))')
        result = fixture.run(sys.executable, '-B', '-c', script, json.dumps(record),
                             cwd=self.repo / 'tools', env=self.env)
        self.assertEqual(json.loads(result.stdout), ['swipe-review'])
        disabled = fixture.run(sys.executable, '-B', '-c', script, json.dumps(record),
                               cwd=self.repo / 'tools', env=dict(self.env, SKILLS_PERSON_ROOT=''))
        self.assertEqual(json.loads(disabled.stdout), [])

    def test_unknown_ownership_is_not_inferred_from_missing_source(self):
        self.prepare_retirement()
        sys.path.insert(0, str(self.repo / 'tools'))
        from skill_scoped import record_digest
        record = self.record()
        record['skills']['swipe-review'].pop('owner')
        record['digest'] = record_digest(record['skills'])
        manifest = self.shelf / '.release-manifest.json'
        manifest.chmod(0o644)
        manifest.write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')
        manifest.chmod(0o444)
        (self.repo / 'manifests/shipped.yaml').write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')
        for turn in range(2):
            self.page.write_text(self.page.read_text() + '\nAnother checked change.\n')
            self.commit('Person edits close ' + str(turn))
            self.cli('ship', '--skill', 'close', *self.overrides)
            self.assertNotIn('owner', self.record()['skills']['swipe-review'])
            self.assertTrue((self.shelf / 'swipe-review/SKILL.md').is_file())
            self.assertNotIn('swipe-review', self.record()['removed'])
        refused = self.cli('ship', '--skill', 'swipe-review', *self.overrides, ok=False)
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn('no source or proven person retirement', refused.stderr)
        self.assertTrue((self.shelf / 'swipe-review/SKILL.md').is_file())

    def test_uncommitted_retirement_cannot_change_the_shelf(self):
        self.prepare_retirement()
        before = self.record()
        page = self.person / 'retired/swipe-review/SKILL.md'
        page.write_text(page.read_text() + '\nUncommitted retirement edit.\n')
        refused = self.cli('ship', '--skill', 'close', *self.overrides, ok=False)
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn('Commit the person skill removal', refused.stderr)
        self.assertEqual(before, self.record())

    def test_drift_hold_lasts_until_the_owner_changes_the_source(self):
        sys.path.insert(0, str(self.repo / 'tools'))
        from skill_scoped import record_digest
        import skill_ship
        name = 'close'
        self.env['SKILLS_PERSON_ROOT'] = ''  # a product skill only; no person copy
        source = self.repo / 'skills' / name
        extra = source / 'references/extra.md'
        extra.parent.mkdir(exist_ok=True)
        extra.write_text('An extra source file the shelf never shipped.\n')
        fixture.run('git', '-C', self.repo, 'add', '-A', 'skills/' + name)
        fixture.run('git', '-C', self.repo, 'commit', '-q', '-m', 'Extra source file')
        fixture.run('git', '-C', self.repo, 'push', '-q', 'origin', 'main')
        # The record holds the skill, the way record-build marks a source with extra files.
        record = self.record()
        digest, count = skill_ship.digest_tree(source)
        record['skills'][name].update(source_digest=digest, source_file_count=count,
                                      source_drift='hold until the owner reconciles these extra source files')
        record['digest'] = record_digest(record['skills'])
        manifest = self.shelf / '.release-manifest.json'
        manifest.chmod(0o644); manifest.write_text(json.dumps(record, indent=2, sort_keys=True) + '\n'); manifest.chmod(0o444)
        (self.repo / 'manifests/shipped.yaml').write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')
        canary = fixture.PROOF / 'drift-canary.py'
        canary.write_text('print("close: present")\n')
        overrides = [item for runtime in ['claude', 'codex', 'hermes']
                     for item in ['--canary-command', runtime + '=' + sys.executable + ' -B ' + str(canary)]]
        refused = self.cli('ship', '--skill', name, *overrides, ok=False)
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn('extra unshipped source files', refused.stderr)
        # The owner reconciles: the source goes back to the shipped bytes, and the ship clears the hold.
        fixture.run('git', '-C', self.repo, 'rm', '-q', 'skills/' + name + '/references/extra.md')
        fixture.run('git', '-C', self.repo, 'commit', '-q', '-m', 'Owner reconciles')
        fixture.run('git', '-C', self.repo, 'push', '-q', 'origin', 'main')
        shipped = self.cli('ship', '--skill', name, *overrides)
        self.assertIn('shipped ' + name, shipped.stdout)
        entry = self.record()['skills'][name]
        self.assertNotIn('source_drift', entry)
        self.assertEqual(entry['owner'], 'product')

    def test_skill_hidden_from_the_model_ships_when_claude_lists_it(self):
        # T675: to-tickets sets disable-model-invocation, so the model says absent; Claude's own list decides.
        self.env['SKILLS_PERSON_ROOT'] = ''
        page = self.repo / 'skills/close/SKILL.md'
        page.write_text(page.read_text().replace('\n---\n', '\ndisable-model-invocation: true\n---\n', 1))
        fixture.run('git', '-C', self.repo, 'commit', '-q', '-am', 'close is hidden from the model')
        fixture.run('git', '-C', self.repo, 'push', '-q', 'origin', 'main')
        claude = fixture.PROOF / 'claude-stream.py'
        claude.write_text('import json\nprint(json.dumps(dict(type="system", subtype="init", skills=["close"])))\n'
                          'print(json.dumps(dict(type="result", result="close: absent")))\n')
        plain = fixture.PROOF / 'plain-canary.py'
        plain.write_text('print("close: present")\n')
        overrides = ['--canary-command', 'claude=' + sys.executable + ' -B ' + str(claude)]
        for runtime in ('codex', 'hermes'):
            overrides += ['--canary-command', runtime + '=' + sys.executable + ' -B ' + str(plain)]
        shipped = self.cli('ship', '--skill', 'close', *overrides)
        self.assertIn('shipped close', shipped.stdout)
        self.assertEqual(page.read_bytes(), (self.shelf / 'close/SKILL.md').read_bytes())

    def test_trigger_plan_reads_the_person_repository(self):
        self.commit('Person copy of close')
        base = self.git('-C', self.person, 'rev-parse', 'HEAD').stdout.strip()
        self.page.write_text(self.page.read_text() + '\nOne more line.\n')
        self.commit('Change close')
        plan = fixture.run(sys.executable, '-B', self.repo / 'tools/catalog_state.py', 'trigger-plan',
                           '--dojo', self.repo, '--source', self.person, '--hook', 'post-commit',
                           '--base', base, env=self.env)
        self.assertEqual(plan.stdout.splitlines()[1:], ['close'])

    def test_install_trigger_puts_the_person_hooks_in_place(self):
        self.commit('Person copy of close')
        installed = self.cli('install-trigger')
        report = json.loads(installed.stdout)
        self.assertEqual(report['person_hooks'], {'post-commit': 'current', 'post-merge': 'current'})
        hook = (self.person / '.git/hooks/post-commit').read_text()
        self.assertIn('SKILLS_SOURCE_REPO', hook)
        self.assertIn(str(self.repo / 'tools/skill-ship-trigger.sh'), hook)
        self.assertEqual(self.cli('install-trigger', '--check').returncode, 0)


if __name__ == '__main__':
    unittest.main()
