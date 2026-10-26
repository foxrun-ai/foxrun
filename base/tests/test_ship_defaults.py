"""Regression proof for installed manifests and missing optional tools."""

import sys as _fox_sys
from pathlib import Path as _FoxPath
_fox_root = _FoxPath(__file__).resolve().parents[2]
_fox_sys.path.insert(0, str(_fox_root))
from base.tests.support import setup as _fox_test_setup
from base.tests.support import shipped_paths
_fox_test_setup()
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'base')]
import install_workspace as installer

class ShipDefaults(unittest.TestCase):
    def test_base_manifest_uses_frozen_workspace_paths(self):
        data = json.loads((ROOT / 'base/install.json').read_text())
        destinations = {r['to'] for r in data['files']}
        self.assertNotIn('SCHEMA.md', destinations)
        self.assertNotIn('CONCEPTS.md', destinations)
        self.assertIn('GLOSSARY.md', destinations)
        self.assertIn('history/handoffs/.gitkeep', destinations)
        self.assertIn('history/LOG.md', destinations)
        self.assertFalse(any(d.startswith(('snapshots/', 'outputs/', 'handoffs/', 'docs/')) for d in destinations))
        for row in data['files']:
            self.assertTrue((ROOT / 'base' / row['from']).is_file(), row)

    def test_installer_accepts_config_and_current_packs(self):
        self.assertEqual(installer.safe_destination('config/design.md'), 'config/design.md')
        modules = installer.parse_modules('base,work,memory,events,decisions', 'personal')
        self.assertIn('memory', modules)
        for module in modules:
            data, path = installer.load_manifest(ROOT, module)
            self.assertTrue(path.is_file())
        for unsafe in ('config/credentials.json', 'config/.env', '.codex/settings.json', 'config/settings.json'):
            with self.assertRaises(installer.InstallError):
                installer.safe_destination(unsafe)

    def test_lookup_has_a_product_path_specification(self):
        import lookup
        with patch.object(lookup, 'SPEC', ROOT / 'base/workspace-spec.md'):
            self.assertTrue(list(lookup.path_rules()))
            self.assertTrue(lookup.dictionary(None)[0])

    def test_recovery_proof_missing_fixture_is_explicit(self):
        result = subprocess.run(['/usr/bin/python3', '-B', str(ROOT / 'base/prove_recovery_bundle.py'),
                                 '--fixture-support', str(ROOT / 'absent-fixture.py')],
                                cwd=ROOT, text=True, capture_output=True)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn('--fixture-support PATH', result.stderr)
        self.assertNotIn('Traceback', result.stderr)

    def test_empty_proposal_block_does_not_consume_the_next_block(self):
        import table
        text = '```gated-transitions\n```\n\n```approval-locks\npeople.agreements: version\n```\n'
        self.assertEqual(table.machine_block(text, 'gated-transitions'), [])
        self.assertEqual(table.machine_block(text, 'approval-locks'), ['people.agreements: version'])

    def test_table_has_product_proposal_rules(self):
        # The rules file stays in base (live readers); People's own copy ships with Small Talk.
        self.assertTrue((ROOT / 'base/proposal-rules.md').is_file())
        self.assertIn('people.agreements:', (ROOT / 'base/proposal-rules.md').read_text())

    def test_core_ships_no_people_module(self):
        # g-people-ships-with-small-talk (231264d): local people/ is outside the shipped core.
        self.assertFalse(any('people' == path.relative_to(ROOT).parts[0] for path in shipped_paths(ROOT)))

    def test_catalog_template_installs(self):
        self.check_template('catalog')

    def test_models_template_installs(self):
        self.check_template('models')

    def test_modules_template_installs(self):
        self.check_template('modules')

    def check_template(self, stem):
        from base.install_system import install_configuration
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            install_configuration(home, 'avery')
            source = ROOT / 'config/templates' / (stem + '.yaml')
            if stem == 'models':
                source = ROOT / 'config/models.yaml'
            self.assertEqual((home / 'config' / (stem + '.yaml')).read_bytes(),
                             source.read_bytes())

    def test_design_pages_install_under_config(self):
        # T669 (9b0f89d): local design/ does not make the product ship design pages.
        self.assertFalse(any('design' == path.relative_to(ROOT).parts[0] for path in shipped_paths(ROOT)))

    def test_dream_without_jev_skips_the_model_half_with_a_clear_message(self):
        # run is the whole night. With no model runner the code half still runs and the model half is skipped.
        # --dry-run keeps this test from writing: the code half lists its steps and runs none.
        env = dict(os.environ)
        env.pop('FOXRUN_JEV_RUNNER', None)
        result = subprocess.run(['/usr/bin/python3', '-B', str(ROOT / 'memory/dream.py'), 'run', '--dry-run'],
                                cwd=ROOT, env=env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('model half: skipped', result.stdout)
        self.assertNotIn('Traceback', result.stderr)  # No configured model is a normal code-only run.
        self.assertNotIn('Traceback', result.stderr)

    def test_turn_tag_without_jev_returns_clear_message(self):
        self.check_optional_runner('turn_tag')

    def check_optional_runner(self, stem):
        env = dict(os.environ)
        env.pop('FOXRUN_JEV_RUNNER', None)
        result = subprocess.run(['/usr/bin/python3', '-B', str(ROOT / 'memory' / (stem + '.py'))],
                                cwd=ROOT, env=env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertNotIn('Traceback', result.stderr)  # No configured model is a normal code-only run.
        self.assertNotIn('Traceback', result.stderr)
