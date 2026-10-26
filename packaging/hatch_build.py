"""Hatch build hook: ship the files in product-manifest.tsv and install.py's STARTERS (T873).

The wheel puts the product tree in foxrun/product/ and the command in
foxrun/__init__.py. The sdist keeps the tree at its own paths.
"""
from __future__ import annotations

import ast
import csv
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version, build_data):
        root = Path(self.root)
        with (root / 'product-manifest.tsv').open(encoding='utf-8', newline='') as handle:
            paths = [row['path'] for row in csv.DictReader(handle, delimiter='\t')]
        paths.append('product-manifest.tsv')
        # Starters are read from the tree at install but are not manifest rows; read them without running install.py.
        for node in ast.parse((root / 'install.py').read_text(encoding='utf-8')).body:
            if isinstance(node, ast.Assign) and any(getattr(target, 'id', None) == 'STARTERS' for target in node.targets):
                paths.extend(ast.literal_eval(node.value))
        prefix = 'foxrun/product/' if self.target_name == 'wheel' else ''
        for path in paths:
            source = root / path
            if not source.is_file():
                raise ValueError('product-manifest.tsv lists a missing file: ' + path)
            build_data['force_include'][str(source)] = prefix + path
        if self.target_name == 'wheel':
            # force_include maps each source once, so the command replaces its product row here.
            build_data['force_include'][str(root / 'packaging/foxrun_cli.py')] = 'foxrun/__init__.py'
