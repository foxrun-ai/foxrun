"""No owner-specific names in shipped text; configured routing has no fixed owner."""

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
import re
import tempfile
import unittest
from unittest.mock import patch
from base import person
ROOT=Path(__file__).resolve().parents[2]
from base.tests.privacy_support import patterns
PATTERNS = patterns()

def manifest_names():
    """The shipped file list: product-manifest.tsv in source, base/product-manifest.tsv once installed."""
    import csv
    for manifest in (ROOT / 'product-manifest.tsv', ROOT / 'base/product-manifest.tsv'):
        if manifest.is_file():
            with manifest.open() as stream:
                return {row['path'] for row in csv.DictReader(stream, delimiter='\t')}
    return None


SHIPPED = manifest_names()


def shipped(path):
    if not path.is_file(): return False
    if SHIPPED is not None:
        # Every listed path ships, tests and fixtures too, so every listed path is scanned.
        return path.relative_to(ROOT).as_posix() in SHIPPED
    parts=path.relative_to(ROOT).parts
    if 'tests' in parts or 'not-shipped' in parts or '.git' in parts or '__pycache__' in parts: return False
    if path.name.endswith('_tests.py'): return False
    if len(parts)>2 and parts[0]=='modules':
        manifest=ROOT/'modules'/parts[1]/'install.json'
        if manifest.exists() and json.loads(manifest.read_text()).get('ships') is False: return False
    return True

class Privacy(unittest.TestCase):
    def test_no_owner_terms_in_shipped_files(self):
        hits=[]
        # T742: a product audit reads manifest paths, not local files in the installed home.
        for path in shipped_paths(ROOT):
            if not shipped(path) or path.suffix in ('.gz','.pyc'): continue
            if any(x in path.name.lower() for x in ('.env','credential','secret','token','auth')): continue
            text=path.read_text().replace('--person-words','')
            for kind, pattern in PATTERNS:
                if kind not in ("email", "phone", "uuid") and re.search(pattern,text,re.I):hits.append((str(path.relative_to(ROOT)),kind))
        self.assertEqual(hits,[])
    def test_configured_workspace_roles_routing_and_functions(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'config').mkdir()
            (root/'config/person.json').write_text(json.dumps({'name':'avery','workspaces':['cedar-lab'],
                'default_workspace':'cedar-lab','personal_workspace':'cedar-lab',
                'workspace_settings':{'cedar-lab':{'organization':'cedar','lead':'director','functions':['support']}}}))
            with patch.dict(os.environ,{'FOXRUN_HOME':str(root),'FOXRUN_PERSON':'avery'}):
                self.assertEqual(person.workspace(),'cedar-lab')
                self.assertEqual(person.workspace_setting('cedar-lab','lead'),'director')
                self.assertEqual(person.workspace_setting('cedar-lab','organization'),'cedar')
                self.assertEqual(person.workspace_setting('cedar-lab','functions'),['support'])
                self.assertEqual(person.render_sql("SELECT '@system_workspace@'"),"SELECT 'cedar-lab'")
                from events import session_run
                portfolio=root/'portfolio'; location=portfolio/'cedar-lab';location.mkdir(parents=True)
                tracker=location/'cedar-lab.sqlite';tracker.write_text('synthetic tracker')
                with patch.dict(os.environ, {'FOX_SESSION_TRACKED_ROOT':str(portfolio)}):
                    self.assertEqual(session_run.tracker_from(str(location)),tracker.resolve())
