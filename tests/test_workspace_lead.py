#!/usr/bin/env python3
"""T784: generated workspace lead boots; every install stays under staging."""
import csv
import json
import os
import pwd
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

TREE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TREE))
if not (TREE / 'install.py').is_file():
    raise unittest.SkipTest('installer tests run from source only')
import install

STAGING = (Path.home() / '.local/state/foxrun/staging').resolve()
TEMPLATE = 'config/templates/workspace-lead/SKILL.md'


class WorkspaceLead(unittest.TestCase):
    def setUp(self):
        STAGING.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='T784-test-', dir=STAGING)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / 'home'
        self.portfolio = self.root / 'portfolio'
        self.workspace = 'sample-shop'
        target = self.home / TEMPLATE
        target.parent.mkdir(parents=True)
        target.write_bytes((TREE / TEMPLATE).read_bytes())
        self.folder = self.portfolio / self.workspace
        self.folder.mkdir(parents=True)

    def fill(self, workspace=None, runtime_roots=()):
        return install.install_workspace_lead(self.home, self.portfolio,
                                              workspace or self.workspace, runtime_roots)

    def snapshot(self):
        return {str(p.relative_to(self.root)): (('link', os.readlink(p)) if p.is_symlink()
                else ('file', p.read_bytes(), p.stat().st_mtime_ns) if p.is_file()
                else ('dir', p.stat().st_mtime_ns)) for p in self.root.rglob('*')}

    def test_fresh_fill_uses_local_runtime_routes(self):
        self.assertTrue(self.fill())
        source = self.folder / 'skills' / self.workspace / 'SKILL.md'
        text = source.read_text()
        self.assertIn('name: sample-shop\n', text)
        self.assertIn(str(self.home / 'foxrun.py'), text)
        self.assertIn(str(self.folder / 'team/TEAM.md'), text)
        self.assertNotRegex(text, r'<home>|<portfolio>|<workspace>')
        for native in ('.agents/skills', '.claude/skills'):
            self.assertEqual(source.read_bytes(), (self.folder / native / self.workspace / 'SKILL.md').read_bytes())
        before = self.snapshot()
        self.assertFalse(self.fill())
        self.assertEqual(before, self.snapshot())

    def test_taken_name_changes_nothing(self):
        for relative in ('portfolio/sample-shop/skills', 'portfolio/sample-shop/.agents/skills',
                         'portfolio/sample-shop/.claude/skills', 'portfolio/sample-shop/.codex/skills',
                         'home/skills', 'home/skillwright/skills', 'runtime/skills'):
            with self.subTest(relative=relative):
                holder = self.root / relative / self.workspace
                holder.mkdir(parents=True)
                page = holder / 'SKILL.md'
                page.write_text('name: sample-shop\nExisting context rules.\n')
                before = self.snapshot()
                self.assertFalse(self.fill(runtime_roots=[self.root / 'runtime/skills']))
                self.assertEqual(before, self.snapshot())
                # Remove only this test's holder, so the next subtest tests its own route.
                page.unlink()
                holder.rmdir()

    def test_broken_link_reserves_the_name(self):
        root = self.folder / 'skills'
        root.mkdir()
        (root / self.workspace).symlink_to('absent')
        before = self.snapshot()
        self.assertFalse(self.fill())
        self.assertEqual(before, self.snapshot())

    def test_linked_route_is_refused_before_any_write(self):
        elsewhere = self.root / 'elsewhere'
        elsewhere.mkdir()
        (self.folder / '.agents').symlink_to(elsewhere)
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'symlink'):
            self.fill()
        self.assertEqual(before, self.snapshot())

    def test_no_workspace_name_is_skipped(self):
        # No name is special: the owner's own workspace name gets a lead boot like any other.
        (self.portfolio / 'foxrun-hq').mkdir()
        self.assertTrue(self.fill('foxrun-hq'))
        self.assertIn('name: foxrun-hq\n', (self.portfolio / 'foxrun-hq/skills/foxrun-hq/SKILL.md').read_text())

    def test_team_members_get_no_skill(self):
        team = self.folder / 'team'
        team.mkdir()
        (team / 'TEAM.md').write_text('Lead: lead-sample-shop\nMembers: builder, researcher\n')
        self.fill()
        for native in ('skills', '.agents/skills', '.claude/skills'):
            self.assertEqual([self.workspace], sorted(p.name for p in (self.folder / native).iterdir()))

    def test_template_is_generic_and_orders_boot_reads(self):
        text = (TREE / TEMPLATE).read_text()
        names = re.split(r'[ ._-]+', pwd.getpwuid(os.getuid()).pw_name.lower())
        for name in names:
            if len(name) > 2:
                self.assertNotIn(name, text.lower())
        self.assertNotRegex(text.lower(), r'/users/|/home/|~/|sample-shop|cedar-shop|studio|architect|chief')
        terms = ['python3 "<home>/foxrun.py" start --workspace <workspace>',
                 '<portfolio>/<workspace>/AGENTS.md', '<portfolio>/<workspace>/team/TEAM.md',
                 '<portfolio>/<workspace>/history/handoffs/']
        positions = [text.index(term) for term in terms]
        self.assertEqual(sorted(positions), positions)
        self.assertIn('before the first reply', text)
        self.assertIn('no handoff', text)

    def test_no_personal_workspace_skill_is_shipped(self):
        with (TREE / 'product-manifest.tsv').open() as stream:
            paths = [row['path'] for row in csv.DictReader(stream, delimiter='\t')]
        self.assertIn(TEMPLATE, paths)
        self.assertFalse(any(re.search(r'(?:^|/)(?:sample-shop|cedar-shop|studio)/SKILL.md$', p) for p in paths))

    def test_staged_install_and_clean_process_boot(self):
        home = self.root / 'installed-home'
        portfolio = self.root / 'installed-portfolio'
        user = self.root / 'user'
        user.mkdir()
        env = {k: v for k, v in os.environ.items()
               if not k.startswith('FOXRUN_') and k not in ('PYTHONPATH', 'PYTHONHOME')}
        env.update(HOME=str(user), PYTHONDONTWRITEBYTECODE='1')
        command = [sys.executable, '-B', str(TREE / 'install.py'), '--home', str(home),
                   '--portfolio', str(portfolio), '--workspace', self.workspace,
                   '--runtime-home', str(self.root / 'runtimes'), '--yes', '--no-schedule']
        result = subprocess.run(command, cwd=TREE, env=env, text=True, capture_output=True, timeout=180)
        self.assertEqual(0, result.returncode, result.stdout[-5000:] + result.stderr)
        self.assertIn('Doctor: 0 failed', result.stdout)
        for workspace in (self.workspace, 'atlas'):
            for native in ('skills', '.agents/skills', '.claude/skills'):
                self.assertTrue((portfolio / workspace / native / workspace / 'SKILL.md').is_file())
        handoffs = portfolio / self.workspace / 'history/handoffs'
        (handoffs / '2026-01-01-001-old.md').write_text('# Old\n')
        (handoffs / '2026-01-02-001-new.md').write_text('# New\n\n## Open Items\n\nSample open item.\n')
        (handoffs / '2026-01-03-001-new.md.coverage.md').write_text('Coverage only.\n')
        # A new Python process executes the generated command, with no inherited session context.
        # This rehearses executable instructions; it is not a model-session acceptance test.
        code = '''import json,re,shlex,subprocess,sys
from pathlib import Path
folder=Path(sys.argv[1]); skill=folder/'.agents/skills'/folder.name/'SKILL.md'
text=skill.read_text(); command=re.search(r'```sh\\n(.*?)\\n',text).group(1).strip()
started=subprocess.run(shlex.split(command),text=True,capture_output=True,check=True)
reads=[folder/'AGENTS.md',folder/'team/TEAM.md']
choices=[p for p in (folder/'history/handoffs').glob('*.md')
         if p.is_file() and not p.is_symlink() and not p.name.startswith('.') and not p.name.endswith('.coverage.md')]
reads.append(max(choices,key=lambda p:p.name))
assert all(p.read_text() for p in reads)
print(json.dumps(dict(start=started.stdout,reads=[str(p) for p in reads])))
'''
        boot = subprocess.run([sys.executable, '-B', '-c', code, str(portfolio / self.workspace)],
                              cwd=self.root, env=env, text=True, capture_output=True, timeout=60)
        self.assertEqual(0, boot.returncode, boot.stderr)
        proof = json.loads(boot.stdout)
        self.assertIn('Workspace: ' + self.workspace, proof['start'])
        self.assertEqual('2026-01-02-001-new.md', Path(proof['reads'][-1]).name)


if __name__ == '__main__':
    unittest.main()
