"""All default workspace installer paths honor the same shipping marks."""

import sys as _fox_sys
from pathlib import Path as _FoxPath
_fox_root = _FoxPath(__file__).resolve().parents[2]
_fox_sys.path.insert(0, str(_fox_root))
from base.tests.support import setup as _fox_test_setup
_fox_test_setup()
from contextlib import closing
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from base import person, install_workspace
from base.distribution import install, sample_workspace
from base.tests.test_install_roster_round7 import manifest_plan

ROOT = Path(__file__).resolve().parents[2]
EXCLUDED = {'design', 'commerce', 'amazon', 'ugc', 'tiktok-shop', 'treasury'}


class InstallPacks(unittest.TestCase):
    def assert_core_only(self, db):
        installed = {r[0] for r in db.execute('SELECT m.name FROM base_installs i JOIN base_modules m ON m.id=i.module')}
        self.assertFalse(installed & EXCLUDED, installed)
        # The core holds no commerce table at all; the pack makes them (g-business-packs-do-not-ship).
        for table in ('commerce_accounts', 'commerce_products', 'commerce_skus'):
            self.assertEqual(db.execute('SELECT count(*) FROM sqlite_schema WHERE name=?', (table,)).fetchone()[0], 0)

    def test_sample_default(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'FOXRUN_HOME': folder, 'FOXRUN_PERSON': 'avery'}):
            fixture = json.loads((ROOT / 'base/distribution/sample/rows.json').read_text())
            with closing(sample_workspace.build_database(ROOT / 'base', fixture)) as db:
                self.assert_core_only(db)

    def test_distribution_default(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'FOXRUN_HOME': folder, 'FOXRUN_PERSON': 'avery'}):
            home = Path(folder).resolve()
            install.install(home, 'round7-test')
            with closing(person.connect(home / '.local/share/foxrun/data.db')) as db:
                self.assert_core_only(db)

    def test_manifest_default(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'FOXRUN_HOME': folder, 'FOXRUN_PERSON': 'avery'}):
            root = Path(folder).resolve()
            plan = manifest_plan(root)
            self.assertFalse(set(plan['modules']) & EXCLUDED, plan['modules'])
            install_workspace.apply_plan(plan)
            # T714: the workspace installer builds no database; the system data.db holds every table.
            self.assertFalse((root / 'target/data.db').exists())


if __name__ == '__main__':
    unittest.main()
