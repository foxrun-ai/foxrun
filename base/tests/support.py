"""Self-contained made-up person fixture for module discovery."""
import atexit
import csv
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import sys

_fixture = None


def shipped_paths(root):
    """Use the product list, never a walk of an installed person's home."""
    root = Path(root)
    for name in ('product-manifest.tsv', 'base/product-manifest.tsv'):
        manifest = root / name
        if manifest.is_file():
            with manifest.open(newline='') as stream:
                return [root / row['path'] for row in csv.DictReader(stream, delimiter='\t')]
    raise FileNotFoundError('product manifest is missing')


def setup():
    # Recheck 2 (T742): append, never prepend. A live home keeps old copies such as
    # apply_program_schema.py in archive/; first on the path, they shadowed the live work/ code.
    sys.path.append(str(Path(__file__).resolve().parents[2] / 'archive/one-time-scripts'))
    global _fixture
    if _fixture is not None:
        return
    _fixture = tempfile.TemporaryDirectory(prefix='suite-person-')
    # Existing regression modules share test_work helpers during plain discovery.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'work/tests'))
    atexit.register(_fixture.cleanup)
    root = Path(_fixture.name).resolve()
    for folder in ('home', 'system/config', 'state', 'portfolio'):
        (root / folder).mkdir(parents=True)
    os.environ.update(FOXRUN_HOME=str(root / 'system'),
                      FOXRUN_PORTFOLIO=str(root / 'portfolio'),
                      FOXRUN_STATE=str(root / 'state'), FOXRUN_PERSON='person')
    config = {
        'name': 'person', 'private_terms': ['sample-family'],
        'workspaces': ['cedar-shop', 'system-workspace', 'sample-finance', 'personal-workspace',
                       'career-workspace', 'venture-workspace', 'runtime-workspace'],
        'default_workspace': 'system-workspace', 'system_workspace': 'system-workspace',
        'shop_workspace': 'cedar-shop', 'personal_workspace': 'personal-workspace',
        'career_workspace': 'career-workspace', 'venture_workspace': 'venture-workspace',
        'runtime_workspace': 'runtime-workspace', 'untracked_workspaces': ['excluded_workspace'],
        'session_workspaces': ['system-workspace', 'cedar-shop'],
        'workspace_settings': {
            'system-workspace': {'organization': 'foxrun', 'lead': 'chief-of-staff', 'filter_functions': True},
            'cedar-shop': {'lead': 'cedar-shop-lead', 'functions': ['amazon', 'amazon-na', 'amazon-eu', 'ugc', 'tiktok-shop']}},
        'import_marks': {'system_tracker': 'system-workspace-tracker',
                         'shop_tracker': 'cedar-shop-legacy-tracker-M5',
                         'approval': 'system-workspace:approvals:199',
                         'comment': 'system-workspace:comments:3161'}}
    (root / 'system/config/person.json').write_text(json.dumps(config) + '\n')
    # T649 fix: synthetic signers have real identities in the isolated test home.
    (root / 'system/agents').mkdir()
    for seat in ('architect', 'chief-of-staff', 'observer', 'person'):
        identity = {'type': 'agent-soul', 'id': seat}
        (root / 'system/agents' / (seat + '.md')).write_text(
            '---\n' + json.dumps(identity) + '\n---\n# ' + seat + '\n')
    os.environ.setdefault('FOXRUN_PROPOSAL_RULES', str(Path(__file__).parent / 'fixtures/proposal-rules.md'))
    from base.person import connect
    sqlite3.connect = connect
