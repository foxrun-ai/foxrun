"""Accept product config while refusing the editor's private state."""

import sys as _fox_sys
from pathlib import Path as _FoxPath
_fox_root = _FoxPath(__file__).resolve().parents[2]
_fox_sys.path.insert(0, str(_fox_root))
from base.tests.support import setup as _fox_test_setup
_fox_test_setup()
import unittest
from base.install_workspace import safe_destination, InstallError
class DestinationProtection(unittest.TestCase):
    def test_editor_state_stays_protected(self):
        for path in ('.obsidian/workspace.json', 'wiki/.obsidian/state.json'):
            with self.assertRaises(InstallError): safe_destination(path)
        self.assertEqual(safe_destination('config/design/brand.md'), 'config/design/brand.md')
