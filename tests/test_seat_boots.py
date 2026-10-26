#!/usr/bin/env python3
"""T765: default seat boots ship without a person's name and install create-only."""
import contextlib
import csv
import hashlib
import io
import os
import json
import pwd
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

TREE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TREE))
if not (TREE / 'install.py').is_file():
    raise unittest.SkipTest('installer tests run from source only')
import install

# A synthetic forbidden-person marker and the host account name stand in for the source owner.
FORBIDDEN_PERSON = 'Wren Example'
_ACCOUNT = re.split(r'[ ._-]+', pwd.getpwuid(os.getuid()).pw_name)[0]
SOURCE_PERSON = re.compile('|'.join(re.escape(v) for v in (FORBIDDEN_PERSON, _ACCOUNT) if len(v) > 2), re.I)
SKILLS = ('chief', 'architect', 'keeper', 'toolsmith', 'skillwright', 'scout', 'adviser')


class SeatBoots(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='T765-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.home = self.root / 'home'
        self.native = self.root / 'runtime/skills'
        for skill in SKILLS:
            shutil.copytree(TREE / 'config/templates' / skill,
                            self.home / 'config/templates' / skill)

    def fill(self):
        return install.install_seat_boots(self.home, 'avery', [self.native])

    def snapshot(self):
        return {str(p.relative_to(self.root)): ('link', os.readlink(p)) if p.is_symlink()
                else ('file', p.read_bytes(), p.stat().st_mtime_ns) if p.is_file()
                else ('dir', p.stat().st_mtime_ns) for p in self.root.rglob('*')}

    def test_every_template_file_is_generic_and_ships_with_matching_hash(self):
        with (TREE / 'product-manifest.tsv').open() as stream:
            rows = {r['path']: r for r in csv.DictReader(stream, delimiter='\t')}
        for skill in SKILLS:
            source = TREE / 'config/templates' / skill
            self.assertTrue((source / 'SKILL.md').is_file())
            self.assertTrue(list((source / 'replays').glob('*.json')))
            for file in source.rglob('*'):
                if not file.is_file():
                    continue
                raw = file.read_bytes()
                self.assertIsNone(SOURCE_PERSON.search(raw.decode('utf-8', 'replace')), str(file))
                self.assertIn(b'@Person@', raw, str(file))
                row = rows[file.relative_to(TREE).as_posix()]
                self.assertEqual(int(row['bytes']), len(raw))
                self.assertEqual(row['sha256'], hashlib.sha256(raw).hexdigest())

    def test_all_seven_fill_person_on_each_shelf_and_repeat_changes_nothing(self):
        self.assertEqual(list(SKILLS), self.fill())
        for skill in SKILLS:
            source = self.home / 'config/templates' / skill
            for file in source.rglob('*'):
                if not file.is_file():
                    continue
                expected = file.read_text().replace('@Person@', 'Avery')
                for shelf in (self.home / 'skills', self.native):
                    actual = (shelf / skill / file.relative_to(source)).read_text()
                    self.assertEqual(expected, actual)
                    self.assertNotIn('@Person@', actual)
                    self.assertNotRegex(actual, SOURCE_PERSON)
        before = self.snapshot()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual([], self.fill())
        self.assertEqual(before, self.snapshot())
        for skill in SKILLS:
            self.assertIn('Skipped seat boot /' + skill, output.getvalue())

    def test_name_on_any_shelf_is_kept_and_other_seats_install(self):
        for shelf in (self.home / 'skills', self.home / 'skillwright/skills', self.native):
            with self.subTest(shelf=shelf):
                holder = shelf / 'architect'
                holder.mkdir(parents=True)
                page = holder / 'SKILL.md'
                page.write_text('Existing skill. Keep exactly.\n')
                before = page.stat().st_mtime_ns
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    installed = self.fill()
                self.assertNotIn('architect', installed)
                self.assertEqual('Existing skill. Keep exactly.\n', page.read_text())
                self.assertEqual(before, page.stat().st_mtime_ns)
                self.assertIn('Skipped seat boot /architect', output.getvalue())
                for target in (self.home / 'skills', self.native):
                    if target != shelf:
                        self.assertFalse((target / 'architect').exists())
                # Remove only fixture files made by this subtest.
                for target in (self.home / 'skills', self.native):
                    for skill in installed:
                        shutil.rmtree(target / skill)
                shutil.rmtree(holder)

    def test_broken_link_reserves_name(self):
        self.native.mkdir(parents=True)
        (self.native / 'chief').symlink_to('absent')
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertNotIn('chief', self.fill())
        self.assertTrue((self.native / 'chief').is_symlink())
        self.assertFalse((self.home / 'skills/chief').exists())

    def test_linked_shelf_refuses_before_writes(self):
        elsewhere = self.root / 'elsewhere'
        elsewhere.mkdir()
        self.native.parent.mkdir()
        self.native.symlink_to(elsewhere)
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'symlink'):
            self.fill()
        self.assertEqual(before, self.snapshot())

    def test_full_install_calls_seat_step_and_fills_all_copies(self):
        user = self.root / 'user'
        user.mkdir()
        env = {k: v for k, v in os.environ.items()
               if not k.startswith('FOXRUN_') and k not in ('PYTHONPATH', 'PYTHONHOME')}
        env.update(HOME=str(user), PYTHONDONTWRITEBYTECODE='1')
        home = user / '.foxrun'
        runtimes = self.root / 'runtimes'
        result = subprocess.run([sys.executable, '-B', str(TREE / 'install.py'),
            '--home', str(home), '--portfolio', str(user / 'foxrun'), '--person', 'avery',
            '--workspace', 'foxrun-hq', '--runtime-home', str(runtimes), '--yes', '--no-schedule'],
            cwd=TREE, env=env, capture_output=True, text=True, timeout=180)
        self.assertEqual(0, result.returncode, result.stdout[-5000:] + result.stderr)
        self.assertIn('Doctor: 0 failed', result.stdout)
        for shelf in (home / 'skills', runtimes / 'claude/skills', runtimes / 'codex/skills',
                      runtimes / 'agents/skills'):
            for skill in SKILLS:
                text = (shelf / skill / 'SKILL.md').read_text()
                self.assertIn('Avery', text)
                self.assertNotIn('@Person@', text)
                self.assertNotRegex(text, SOURCE_PERSON)
            helper = shelf / 'handoff/bin/handoff-boot'
            self.assertTrue(os.access(helper, os.X_OK), str(helper))
            self.assertIn('Avery', (shelf / 'handoff/SKILL.md').read_text())
            self.assertNotIn('@Person@', (shelf / 'handoff/SKILL.md').read_text())
        boot_env = dict(env, FOXRUN_HOME=str(home), FOXRUN_PORTFOLIO=str(user / 'foxrun'))
        workspace = user / 'foxrun/foxrun-hq'
        helper = home / 'skills/handoff/bin/handoff-boot'
        for skill in SKILLS:
            seat = 'chief-of-staff' if skill == 'chief' else skill
            command = [str(helper), '--seat', seat, '--cwd', str(workspace), '--json']
            result = subprocess.run(command, env=boot_env, stdin=subprocess.DEVNULL,
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual('', result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(seat, report['seat'])
            self.assertEqual('foxrun-hq', report['workspace'])
            self.assertIsNone(report['picked'])
            self.assertIn('no handoff for seat', report['reason'])
            # Check every literal file path in this seat's boot reads.
            reads = (home / 'agents' / (seat + '.md')).read_text().split('### Boot reads', 1)[1]
            reads = reads.replace('${FOXRUN_HOME:-$HOME/.foxrun}', str(home))
            reads = reads.replace('~/', str(user) + '/')
            paths = re.findall(re.escape(str(user)) + r'/[^\s`";]+', reads)
            for path in set(paths):
                if path not in (str(home), str(workspace)):
                    self.assertTrue(Path(path).is_file(), seat + ': ' + path)
            # A zero exit alone is insufficient: prove that the shipped helper selects a note.
            note = workspace / 'history/handoffs' / ('2026-01-01-001-' + seat + '-fixture.md')
            note.write_text('---\ntype: handoff\nworkspace: foxrun-hq\nseat: ' + seat +
                            '\nsession: fixture\n---\nSynthetic boot check.\n')
            result = subprocess.run(command, env=boot_env, stdin=subprocess.DEVNULL,
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual('', result.stderr)
            self.assertEqual(str(note), json.loads(result.stdout)['picked'])


class HandoffProduct(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='T765-handoff-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.home = self.root / 'home'
        self.native = self.root / 'runtime/skills'
        shutil.copytree(TREE / 'skillwright/skills/handoff', self.home / 'skillwright/skills/handoff')

    def test_source_files_ship_with_matching_hashes_and_generic_names(self):
        with (TREE / 'product-manifest.tsv').open() as stream:
            rows = {r['path']: r for r in csv.DictReader(stream, delimiter='\t')}
        for file in (TREE / 'skillwright/skills/handoff').rglob('*'):
            if not file.is_file() or '__pycache__' in file.parts:
                continue
            raw = file.read_bytes()
            self.assertIsNone(SOURCE_PERSON.search(raw.decode('utf-8', 'replace')), str(file))
            row = rows[file.relative_to(TREE).as_posix()]
            self.assertEqual(int(row['bytes']), len(raw))
            self.assertEqual(row['sha256'], hashlib.sha256(raw).hexdigest())

    def test_install_fills_name_keeps_command_modes_and_preserves_repeat(self):
        self.assertTrue(install.install_handoff(self.home, 'avery', [self.native]))
        for shelf in (self.home / 'skills', self.native):
            for file in (self.home / 'skillwright/skills/handoff').rglob('*'):
                if not file.is_file(): continue
                target = shelf / 'handoff' / file.relative_to(self.home / 'skillwright/skills/handoff')
                self.assertEqual(file.read_text().replace('@Person@', 'Avery'), target.read_text())
                self.assertEqual(file.stat().st_mode & 0o777, target.stat().st_mode & 0o777)
            self.assertTrue(os.access(shelf / 'handoff/bin/handoff-boot', os.X_OK))
        before = {str(p): (p.read_bytes(), p.stat().st_mtime_ns)
                  for p in self.root.rglob('*') if p.is_file()}
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(install.install_handoff(self.home, 'other', [self.native]))
        self.assertEqual(before, {str(p): (p.read_bytes(), p.stat().st_mtime_ns)
                                 for p in self.root.rglob('*') if p.is_file()})

    def test_taken_name_on_runtime_shelf_keeps_person_skill(self):
        holder = self.native / 'handoff'
        holder.mkdir(parents=True)
        page = holder / 'SKILL.md'
        page.write_text('Existing handoff.\n')
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(install.install_handoff(self.home, 'avery', [self.native]))
        self.assertEqual('Existing handoff.\n', page.read_text())
        self.assertFalse((self.home / 'skills/handoff').exists())

    def test_setup_skills_ship_and_a_taken_name_is_kept(self):
        for skill in ('thread', 'setup', 'ask'):
            shutil.copytree(TREE / 'skillwright/skills' / skill, self.home / 'skillwright/skills' / skill)
        holder = self.native / 'ask'
        holder.mkdir(parents=True)
        (holder / 'SKILL.md').write_text('Existing ask.\n')
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            results = [install.install_product_skill(self.home, skill, 'avery', [self.native])
                       for skill in ('thread', 'setup', 'ask')]
        self.assertEqual(results, [True, True, False])
        self.assertIn('Skipped product skill /ask', output.getvalue())
        self.assertEqual('Existing ask.\n', (holder / 'SKILL.md').read_text())
        for shelf in (self.home / 'skills', self.native):
            self.assertTrue(os.access(shelf / 'thread/bin/thread', os.X_OK))
            self.assertTrue(os.access(shelf / 'setup/bin/setup', os.X_OK))

    def test_linked_shelf_refuses_before_writes(self):
        elsewhere = self.root / 'elsewhere'
        elsewhere.mkdir()
        self.native.parent.mkdir()
        self.native.symlink_to(elsewhere)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            install.install_handoff(self.home, 'avery', [self.native])
        self.assertFalse((self.home / 'skills/handoff').exists())


if __name__ == '__main__':
    unittest.main()
