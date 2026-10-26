"""Regression tests for the relocation audit, using only temporary inputs."""

import sys as _fox_sys
from pathlib import Path as _FoxPath
_fox_root = _FoxPath(__file__).resolve().parents[2]
_fox_sys.path.insert(0, str(_fox_root))
from base.tests.support import setup as _fox_test_setup
_fox_test_setup()
from pathlib import Path
import importlib.util
import json
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / p) for p in ('base', 'work', 'memory')]


class AuditFixes(unittest.TestCase):
    def test_workspace_wiki_keeps_its_name(self):
        # T681 (846e093): one template home; base/install.json now places wiki/TOPICS.md.
        manifest = json.loads((ROOT / 'base/install.json').read_text())
        self.assertIn('wiki/TOPICS.md', [row['to'] for row in manifest['files']])
        rules = json.loads((ROOT / 'base/workspace-schematic-rules.json').read_text())
        self.assertNotIn('"memory/', json.dumps(rules))
        import dictionary_v11
        self.assertNotIn("'memory/'+folder", Path(dictionary_v11.__file__).read_text())

    def test_release_reads_distribution_in_base(self):
        sys.path.insert(0, str(ROOT / 'base/distribution'))
        import build_release
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'code/foxrun-modules/base/distribution'
            source.mkdir(parents=True)
            # The first absent file must be in the installed source layout.
            with self.assertRaisesRegex(ValueError, 'base/distribution/sample_workspace.py'):
                build_release.build(root, root / 'out')

    def test_release_later_checks_are_named_plainly(self):
        import re
        manifest = json.loads((ROOT / 'base/distribution/release/manifest.json').read_text())
        self.assertIn('Clean-home installation, twice', manifest['later_checks'])
        source = (ROOT / 'base/distribution/build_release.py').read_text()
        built = re.search(r"'later_checks': \[(.*?)\]", source).group(1)
        self.assertIn("'Clean-home installation, twice'", built)
        for text in manifest['later_checks'] + [built]:
            self.assertNotRegex(text, r'\b[TB][0-9]+\b')

    def test_handoff_outside_home_absolute_reference(self):
        import handoff_check
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch.object(Path, 'home', return_value=root / 'home'):
                path = root / 'portfolio/shop/docs/specs/test.md'
                self.assertTrue(handoff_check.mentioned(str(path), path, str(path), root / 'handoff.md'))

    def test_handoff_outside_home_relative_reference(self):
        import handoff_check
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch.object(Path, 'home', return_value=root / 'home'), patch.object(
                    handoff_check._fox_paths, 'portfolio', return_value=root / 'portfolio'):
                path = root / 'portfolio/shop/docs/specs/test.md'
                self.assertTrue(handoff_check.mentioned(str(path), path, 'shop/docs/specs/test.md', root / 'handoff.md'))

    def test_sqlite_snapshot_keeps_pending_rows_on_python39(self):
        from load_history_actions import snapshot_pending
        source = sqlite3.connect(':memory:')
        target = sqlite3.connect(':memory:')
        self.addCleanup(source.close)
        self.addCleanup(target.close)
        source.execute('CREATE TABLE rows (id INTEGER, value TEXT)')
        source.execute("INSERT INTO rows VALUES (7, 'pending')")
        snapshot_pending(source, target)
        self.assertEqual(target.execute('SELECT * FROM rows').fetchall(), [(7, 'pending')])
        self.assertTrue(source.in_transaction)
