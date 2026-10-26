"""The approval rehearsal finds its shipped decisions module directly."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


import sys as _fox_sys
from pathlib import Path as _FoxPath
_fox_root = _FoxPath(__file__).resolve().parents[2]
_fox_sys.path.insert(0, str(_fox_root))
from base.tests.support import setup as _fox_test_setup
_fox_test_setup()

class ApprovalStartup(unittest.TestCase):
    def test_direct_help(self):
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as folder:
            p = subprocess.run(['/usr/bin/python3', '-B', str(root / 'work/approve_rehearsal.py'), '--help'],
                               cwd=folder, env={'HOME': folder, 'FOXRUN_HOME': folder,
                                               'FOXRUN_PERSON': 'avery', 'PYTHONDONTWRITEBYTECODE': '1'},
                               text=True, capture_output=True)
            self.assertEqual(p.returncode, 0, p.stderr)


if __name__ == '__main__':
    unittest.main()
