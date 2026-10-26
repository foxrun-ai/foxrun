"""Expose existing blueprint regressions to plain unittest discovery."""
import importlib
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(Path(__file__).parent), str(ROOT / 'base')]
from base.tests.support import setup
setup()


def load_tests(loader, tests, pattern):
    tests.addTests(loader.loadTestsFromModule(importlib.import_module('v12_tests')))
    for name in ('guard_tests', 'command_tests', 'view_tests', 'regeneration_tests', 'derived_guard_tests'):
        def verify(name=name):
            module = importlib.import_module(name)
            with tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                if name == 'regeneration_tests':
                    shutil.copytree(ROOT / 'base/blueprint', root / 'code/foxrun-modules/base/blueprint')
                    module.verify(root)
                elif name == 'derived_guard_tests':
                    import core
                    from base.tests.addons import BLUEPRINT
                    path = root / 'test.db'
                    core.build(path, BLUEPRINT)  # treasury rows name a People table, so People joins
                    db = core.connect(path, module.CONTEXT)
                    try:
                        module.verify(db, BLUEPRINT)
                    finally:
                        db.close()
                else:
                    # These walk every table, People and pack tables too: load them from their add-ons.
                    from base.tests.addons import BLUEPRINT
                    module.verify(root / 'test.db', BLUEPRINT)
        tests.addTest(unittest.FunctionTestCase(verify, description=name + '.verify'))
    return tests
