#!/usr/bin/env python3
"""Offline day-one proof on five real, nested skills. No agent sessions."""
import csv
import hashlib
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
import tempfile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT
BUILD = ROOT.parent
# Resolved: on macOS the temp folder is behind the /var link, and the shelf checks compare resolved paths.
PROOF = Path(tempfile.mkdtemp(prefix='dayone-release-')).resolve()
HOME = PROOF / 'fake-home'
REPO = HOME / '.foxrun/skillwright'
SHELF = HOME / '.foxrun/skills'
NAMES = ['close', 'fx-asc2', 'runtime-session-search', 'skill-ship', 'skillify']
COMMANDS = []

def run(*command, env=None, cwd=None, ok=True):
    command = [str(x) for x in command]
    assert not any('/Code/skills-dojo' in x or '/.agents' in x for x in command)
    COMMANDS.append(command)
    result = subprocess.run(command, env=env, cwd=cwd, text=True, capture_output=True)
    if ok and result.returncode:
        raise AssertionError(str(command) + '\n' + result.stdout + '\n' + result.stderr)
    return result

# The real skills used as fixtures are the person's own; they live in the person's source (T675).
PERSON = Path(os.environ.get('SKILLS_PERSON_ROOT') or Path(os.environ.get('FOXRUN_PORTFOLIO', '~/foxrun')).expanduser() / 'skillwright')

def fixture_source(name):
    # Person-owned source wins over a product copy in the active release.
    for root in (PERSON, ROOT):
        if (root / 'skills' / name / 'SKILL.md').is_file():
            return root / 'skills' / name
    return ROOT / 'skills' / name

def copy_skill(name, dest):
    source = fixture_source(name)
    shutil.copytree(source, dest, symlinks=True, ignore=shutil.ignore_patterns('.git', '__pycache__', '.cache', 'node_modules', '.env', '.env.*', 'auth.json', 'credentials.json'))
    for file in dest.rglob('*'):
        if file.is_file() and not file.is_symlink():
            file.chmod(0o755 if file.stat().st_mode & 0o111 else 0o644)

def seed_release_gate(system, source_system):
    """Use the real gate and engine with a labelled minimal skill-source fixture policy."""
    (system/'base').mkdir(parents=True,exist_ok=True)
    for name in ['lint.py','lint_gate.py']:shutil.copy2(source_system/'base'/name,system/'base'/name)
    shutil.copytree(source_system/'config/lint',system/'config/lint')
    (system/'config/lint/rules.tsv').write_text('id\twords\tkind\tscope\tlevel\nFIXTURE-BLANK-SKILL\tFixture skill pages contain text.\tblank_page\tsystem:*/skills/**/SKILL.md\terror\n')

def setup():
    PROOF.mkdir(parents=True, exist_ok=True)
    REPO.mkdir(parents=True)
    (REPO / 'skills').mkdir()
    (REPO / 'manifests').mkdir()
    (REPO / 'config').mkdir()
    shutil.copytree(OUT / 'tools', REPO / 'tools')
    shutil.copytree(OUT / 'standards', REPO / 'standards', symlinks=True)
    for name in NAMES:
        copy_skill(name, REPO / 'skills' / name)
    alias=REPO/'skills/skillify/references/skill-law.md'
    assert alias.is_symlink() and os.readlink(alias)=='../../../standards/skill-law.md'
    # Explicit production packaging, after proving that the copied source retains the real alias.
    run(sys.executable,'-B','-c',
        "import sys; from pathlib import Path; import skill_ship; from skill_scoped import package_skill; "
        "[package_skill(skill_ship,Path(sys.argv[1])/'skills'/name,Path(sys.argv[2])/name,Path(sys.argv[1])) for name in sys.argv[3:]]",
        REPO,SHELF,*NAMES,cwd=REPO/'tools')
    assert alias.is_symlink()
    assert not (SHELF/'skillify/references/skill-law.md').is_symlink()
    # Skillify's native-session unit fixtures import Herdr's parser; no Herdr session starts.
    copy_skill('herdr', REPO/'skills/herdr')
    policy = dict(version=1, where={'herdr':'off'}, claude_preserve_physical=[], claude_approval_required={}, host_specific={})
    canonical = REPO.parent / 'config/catalog.yaml'
    canonical.parent.mkdir(parents=True, exist_ok=True)
    canonical.write_text(json.dumps(policy, indent=2) + '\n')
    (REPO / 'config/catalog.yaml').symlink_to('../../config/catalog.yaml')
    (REPO / '.gitignore').write_text('skill-state/\nskill-releases/\n')
    owner = REPO.parent / 'base/catalog.py'; owner.parent.mkdir()
    shutil.copy2(BUILD / 'base/catalog.py', owner)
    seed_release_gate(REPO.parent,BUILD)
    (PROOF/'portfolio').mkdir(exist_ok=True)
    # Five actual skills; one unrelated, unclassified non-skill source.
    unrelated = REPO / 'skills/unclassified-import'
    unrelated.mkdir()
    (unrelated / 'README.md').write_text('Unclassified import; not a skill.\n')
    run('git', 'init', '-q', '-b', 'main', REPO)
    run('git', '-C', REPO, 'config', 'user.name', 'Day-one proof')
    run('git', '-C', REPO, 'config', 'user.email', 'proof@local')
    run('git', '-C', REPO, 'add', '.')
    run('git', '-C', REPO, 'commit', '-q', '-m', 'Five real nested skills')
    origin = PROOF / 'origin.git'
    run('git', 'init', '-q', '--bare', origin)
    run('git', '-C', REPO, 'remote', 'add', 'origin', origin)
    run('git', '-C', REPO, 'push', '-q', '-u', 'origin', 'main')
    env = dict(os.environ, HOME=str(HOME), TMPDIR=str(PROOF / 'tmp'), PYTHONDONTWRITEBYTECODE='1',
               FOXRUN_HOME=str(REPO.parent), FOXRUN_PORTFOLIO=str(PROOF/'portfolio'),
               SKILLS_DOJO_ROOT=str(REPO), SKILLIFY_DOJO_ROOT=str(REPO), SKILLS_PERSON_ROOT='',
               SKILL_RELEASES_ROOT=str(REPO / 'skill-releases'), SKILL_STATE_ROOT=str(REPO / 'skill-state'),
               SKILLS_ACTIVE_PATH=str(SHELF), SKILLS_CLAUDE_ROOT=str(HOME / 'claude-skills'),
               SKILLS_CODEX_ROOT=str(HOME / 'codex-skills'), SKILLS_AGENTS_ROOT=str(HOME / 'agents-skills'),
               SKILLS_PIN_PATH=str(HOME / '.foxrun/agents/execution/skills.yaml'))
    Path(env['TMPDIR']).mkdir()
    run(sys.executable, '-B', '-c', "from pathlib import Path; from catalog_state import approve_existing; approve_existing(Path('..') ,'Fixture baseline')", env=env, cwd=REPO / 'tools')
    for key in ['SKILLS_CLAUDE_ROOT', 'SKILLS_CODEX_ROOT', 'SKILLS_AGENTS_ROOT']:
        root = Path(env[key]); root.mkdir()
        for name in NAMES:
            (root / name).symlink_to(SHELF / name)
    record = PROOF / 'initial-record'
    run(sys.executable, '-B', REPO / 'tools/skill_ship.py', 'record-build', '--source', REPO,
        '--shelf', SHELF, '--output', record, env=env)
    for src, dst in [(record / '.release-manifest.json', SHELF / '.release-manifest.json'),
                     (record / 'shipped.yaml', REPO / 'manifests/shipped.yaml'),
                     (record / 'skills.yaml', Path(env['SKILLS_PIN_PATH'])),
                     (record / 'release-state.json', REPO / 'skill-state/release-state.json')]:
        dst.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(src, dst)
    for file in SHELF.rglob('*'):
        if file.is_file(): file.chmod(0o555 if file.stat().st_mode & 0o111 else 0o444)
    run('git', '-C', REPO, 'add', '.')
    run('git', '-C', REPO, 'commit', '-q', '-m', 'Tool-generated initial record')
    run('git', '-C', REPO, 'push', '-q', 'origin', 'main')
    # These local canaries check bytes at fake consumer links. They start no runtimes.
    canary = PROOF / 'local-canary.py'
    canary.write_text('import os\nfrom pathlib import Path\np=Path(os.environ["SKILLS_ACTIVE_PATH"])/"close/SKILL.md"\nassert "Use the fx-close skill." in p.read_text()\nassert not p.stat().st_mode & 0o222\nprint("close: present")\n')
    overrides = []
    for runtime in ['claude', 'codex', 'hermes']:
        overrides += ['--canary-command', runtime + '=' + sys.executable + ' -B ' + str(canary)]
    return env, overrides

def fresh_proof():
    """Other test modules repoint these globals at their own fixture; start Proof in a new folder."""
    global PROOF, HOME, REPO, SHELF
    PROOF = Path(tempfile.mkdtemp(prefix='dayone-release-')).resolve()
    HOME = PROOF / 'fake-home'
    REPO = HOME / '.foxrun/skillwright'
    SHELF = HOME / '.foxrun/skills'

class Proof(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fresh_proof()
        cls.env, cls.overrides = setup()

    def test_01_check_ship_noop_rollback_and_failure_restore(self):
        old = (SHELF / 'close/SKILL.md').read_bytes()
        oldrecord = (SHELF / '.release-manifest.json').read_bytes()
        olddist = (REPO / 'manifests/shipped.yaml').read_bytes()
        oldpin = Path(self.env['SKILLS_PIN_PATH']).read_bytes()
        untouched = {name: (SHELF / name / 'SKILL.md').read_bytes() for name in NAMES if name != 'close'}
        path = REPO / 'skills/close/SKILL.md'
        # The actual current workflow edits one source line, then skillify checks and marks it active.
        path.write_text(path.read_text().replace('Run the fx-close skill.', 'Use the fx-close skill.'))
        checked = run(sys.executable, '-B', REPO / 'skills/skillify/bin/skillify', 'check', 'close', env=self.env)
        self.assertIn('ready close', checked.stdout)
        run('git', '-C', REPO, 'add', 'skills/close', 'config/catalog.yaml')
        run('git', '-C', REPO, 'commit', '-q', '-m', 'Check one changed line through skillify')
        run('git', '-C', REPO, 'push', '-q', 'origin', 'main')
        ship = REPO / 'tools/skill_ship.py'
        shipped = run(ship, 'ship', '--skill', 'close', *self.overrides, env=self.env)
        self.assertTrue(SHELF.is_symlink())
        self.assertFalse(os.readlink(SHELF).startswith('/'))
        self.assertEqual(path.read_bytes(), (SHELF / 'close/SKILL.md').read_bytes())
        self.assertFalse((SHELF / 'close/SKILL.md').stat().st_mode & 0o222)
        record = json.loads((SHELF / '.release-manifest.json').read_text())
        self.assertNotEqual(oldrecord, (SHELF / '.release-manifest.json').read_bytes())
        self.assertEqual(record, json.loads((REPO / 'manifests/shipped.yaml').read_text()))
        self.assertEqual(record['release_id'], json.loads(Path(self.env['SKILLS_PIN_PATH']).read_text())['release'])
        for name, content in untouched.items():
            self.assertEqual(content, (SHELF / name / 'SKILL.md').read_bytes())
        releases = list((REPO / 'skill-releases').iterdir())
        noop = run(ship, 'ship', '--skill', 'close', *self.overrides, env=self.env)
        self.assertIn('no-op:', noop.stdout)
        self.assertEqual(releases, list((REPO / 'skill-releases').iterdir()))
        rolled = run(ship, 'rollback', '--authorize-reviewed', record['release_id'], env=self.env)
        self.assertFalse(SHELF.is_symlink())
        self.assertEqual(old, (SHELF / 'close/SKILL.md').read_bytes())
        self.assertEqual(oldrecord, (SHELF / '.release-manifest.json').read_bytes())
        self.assertEqual(olddist, (REPO / 'manifests/shipped.yaml').read_bytes())
        self.assertEqual(oldpin, Path(self.env['SKILLS_PIN_PATH']).read_bytes())
        # Fail a local canary after publication; exact directory and record restore.
        fail = PROOF / 'failed-canary.py'; fail.write_text('raise SystemExit(1)\n')
        overrides = ['--canary-command', 'claude=' + sys.executable + ' -B ' + str(fail)] + self.overrides[2:]
        failed = run(ship, 'ship', '--skill', 'close', *overrides, env=self.env, ok=False)
        self.assertNotEqual(failed.returncode, 0)
        self.assertFalse(SHELF.is_symlink())
        self.assertEqual(oldrecord, (SHELF / '.release-manifest.json').read_bytes())
        self.assertEqual(oldpin, Path(self.env['SKILLS_PIN_PATH']).read_bytes())
        # A genuinely unclassified skill cannot block a different named ship.
        imported = REPO / 'skills/unclassified-import/SKILL.md'
        imported.write_text('---\nname: unclassified-import\ndescription: Read this unrelated import.\n---\nRead the unrelated imported note and return its stored text without changing the note.\n')
        preview = run(ship, 'ship', '--skill', 'close', '--dry-run', env=self.env)
        self.assertIn('dry-run: checked close', preview.stdout)
        denied = run(ship, 'ship', '--skill', 'unclassified-import', '--dry-run', env=self.env, ok=False)
        self.assertNotEqual(denied.returncode, 0)
        self.assertIn('Commit the checked skill', denied.stderr)
        # A source without an upstream stops before activation.
        run('git', '-C', REPO, 'branch', '--unset-upstream')
        no_upstream = run(ship, 'ship', '--skill', 'close', *self.overrides, env=self.env, ok=False)
        self.assertNotEqual(no_upstream.returncode, 0)
        self.assertIn('no upstream', no_upstream.stderr)
        self.assertEqual(oldrecord, (SHELF / '.release-manifest.json').read_bytes())
        (PROOF / 'dayone-results.txt').write_text(
            'Five real skills in nested layout: PASS\nOne source line edited, checked by skillify, committed: PASS\n'
            'Single ship: shelf bytes equal source, read-only, relative link: PASS\n'
            'Other four skill pages unchanged: PASS\nRelease record, shipped list, and pin agree: PASS\n'
            'Second ship: no-op, no release added: PASS\nRollback: old shelf bytes and all records restored: PASS\n'
            'Failed synthetic canary: old shelf and records restored: PASS\n'
            'Unclassified unrelated skill: selected preview passes; its own ship refuses: PASS\n'
            'No upstream: ship refuses before shelf activation: PASS\n'
            'Runtime canaries used local byte checks only; no actual runtime activation is claimed.\n'
            + checked.stdout + shipped.stdout + noop.stdout + rolled.stdout)

class RootRoutes(unittest.TestCase):
    def lifecycle(self, linked):
        global PROOF, HOME, REPO, SHELF
        PROOF = Path(tempfile.mkdtemp(prefix='root-route-')).resolve()
        HOME = PROOF / 'fake-home'
        REPO = HOME / '.foxrun/skillwright'
        SHELF = HOME / '.foxrun/skills'
        env, overrides = setup()
        for key in linked:
            root = Path(env[key])
            for name in NAMES:
                (root / name).unlink()
            root.rmdir()
            root.symlink_to(SHELF)
        preserved = []
        for key in ['SKILLS_CLAUDE_ROOT', 'SKILLS_CODEX_ROOT']:
            root = Path(env[key])
            if not root.is_symlink():
                sentinel = root / 'unrelated.txt'
                sentinel.write_text('Owner content.\n')
                preserved.append(sentinel)
        runner = Proof('test_01_check_ship_noop_rollback_and_failure_restore')
        runner.env, runner.overrides = env, overrides
        runner.test_01_check_ship_noop_rollback_and_failure_restore()
        for key in linked:
            self.assertTrue(Path(env[key]).is_symlink())
            self.assertEqual(Path(env[key]).resolve(), SHELF.resolve())
        for path in preserved:
            self.assertEqual(path.read_text(), 'Owner content.\n')

    def test_claude_root_link(self):
        self.lifecycle(['SKILLS_CLAUDE_ROOT'])

    def test_codex_root_link(self):
        self.lifecycle(['SKILLS_CODEX_ROOT'])

    def test_both_root_links(self):
        self.lifecycle(['SKILLS_CLAUDE_ROOT', 'SKILLS_CODEX_ROOT'])

    def test_agents_root_gets_a_link_to_the_shelf(self):
        # T742: skill-ship serves ~/.agents/skills, what Claude and Codex read, by one link per skill to the shelf.
        global PROOF, HOME, REPO, SHELF
        PROOF = Path(tempfile.mkdtemp(prefix='agents-route-')).resolve()
        HOME = PROOF / 'fake-home'
        REPO = HOME / '.foxrun/skillwright'
        SHELF = HOME / '.foxrun/skills'
        env, overrides = setup()
        agents = Path(env['SKILLS_AGENTS_ROOT'])
        (agents / 'close').unlink()
        path = REPO / 'skills/close/SKILL.md'
        path.write_text(path.read_text().replace('Run the fx-close skill.', 'Use the fx-close skill.'))
        run(sys.executable, '-B', REPO / 'skills/skillify/bin/skillify', 'check', 'close', env=env)
        run('git', '-C', REPO, 'add', 'skills/close', 'config/catalog.yaml')
        run('git', '-C', REPO, 'commit', '-q', '-m', 'Check one changed line through skillify')
        run('git', '-C', REPO, 'push', '-q', 'origin', 'main')
        run(REPO / 'tools/skill_ship.py', 'ship', '--skill', 'close', *overrides, env=env)
        self.assertEqual(os.readlink(agents / 'close'), str(SHELF / 'close'))
        self.assertEqual(path.read_bytes(), (agents / 'close/SKILL.md').read_bytes())


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    (PROOF / 'commands.json').write_text(json.dumps(COMMANDS, indent=2) + '\n')
    sys.exit(0 if result.wasSuccessful() else 1)
