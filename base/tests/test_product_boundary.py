"""Shipped code cannot depend on excluded personal tooling."""
import ast
from pathlib import Path
import unittest


import sys as _fox_sys
from pathlib import Path as _FoxPath
_fox_root = _FoxPath(__file__).resolve().parents[2]
_fox_sys.path.insert(0, str(_fox_root))
from base.tests.support import setup as _fox_test_setup
from base.tests.support import shipped_paths
_fox_test_setup()
class ProductBoundary(unittest.TestCase):
    def test_shipped_imports_never_reach_personal_tooling(self):
        root = Path(__file__).resolve().parents[2]
        violations = []
        # T630 (44cee23): excluded code lives outside the core; only shipped imports can cross this boundary.
        for p in shipped_paths(root):
            if p.suffix != '.py' or 'tests' in p.parts or not p.is_file():
                continue
            source = p.read_text()
            for n in ast.walk(ast.parse(source)):
                if isinstance(n, ast.Import):
                    names = [a.name for a in n.names]
                elif isinstance(n, ast.ImportFrom):
                    names = [n.module or '']
                else:
                    continue
                for name in names:
                    if 'not_shipped' in name or 'not-shipped' in name:
                        violations.append((str(p.relative_to(root)), name))
            if 'not-shipped/' in source:
                violations.append((str(p.relative_to(root)), 'dynamic path'))
        self.assertEqual(violations, [])
