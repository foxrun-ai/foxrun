#!/usr/bin/env python3
"""Verify portable homes without using the operator's machine."""

import sys as _fox_sys
from pathlib import Path as _FoxPath
_fox_root = _FoxPath(__file__).resolve().parents[2]
_fox_sys.path.insert(0, str(_fox_root))
from base.tests.support import setup as _fox_test_setup
_fox_test_setup()
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from base import paths


class PortablePathsTests(unittest.TestCase):
    def test_default_homes_follow_empty_home(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'HOME': folder}, clear=True):
            root = Path(folder).resolve()
            self.assertEqual(paths.system_home(), root / '.foxrun')
            self.assertEqual(paths.portfolio(), root / 'foxrun')
            self.assertEqual(paths.state(), root / '.local/state/foxrun')
            self.assertEqual(paths.runs(), root / '.foxrun/runs')
            self.assertEqual(paths.database(), root / '.foxrun/data.db')
            self.assertEqual(paths.workspace('demo'), root / 'foxrun/demo')

    def test_overrides_are_read_for_each_call(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            with patch.dict(os.environ, {'FOXRUN_HOME': str(root/'system'), 'FOXRUN_PORTFOLIO': str(root/'portfolio'), 'FOXRUN_STATE': str(root/'state')}):
                self.assertEqual(paths.database(), root / 'system/data.db')
                self.assertEqual(paths.workspace('demo'), root / 'portfolio/demo')
                self.assertEqual(paths.state(), root / 'state')
                self.assertEqual(paths.runs(), root / 'system/runs')
                os.environ['FOXRUN_HOME'] = str(root/'other')
                self.assertEqual(paths.database(), root / 'other/data.db')
                self.assertEqual(paths.runs(), root / 'other/runs')

    def test_workspace_refuses_path_escape(self):
        for name in ('', '.', '..', '../other', '/tmp', 'one/two', 'one\\two'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                paths.workspace(name)
