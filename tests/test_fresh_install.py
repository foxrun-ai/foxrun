#!/usr/bin/env python3
"""T595: a new person's first session, run end to end on a clean home.

The test copies the commands from INSTALL.md and GUIDE.md as a new person would,
merges the hook entries that install prints, and runs each hook with a test stdin.
HOME is a temporary folder and launchctl is a stub, so nothing touches the real machine.
Run: /usr/bin/python3 -B tests/test_fresh_install.py
"""
import csv
import importlib.util
import json
import os
from pathlib import Path
import pwd
import re
import sqlite3
import subprocess
import tempfile
import unittest

TREE = Path(__file__).resolve().parents[1]
PERSON, WORKSPACE = 'sample-person', 'sample-shop'


def blocks(page, heading):
    """The sh blocks under one heading of a product page, with the example names replaced."""
    text = (TREE / page).read_text().split(heading, 1)[1]
    text = re.split(r'\n## ', text, 1)[0]
    found = re.findall(r'```sh\n(.*?)```', text, re.S)
    return [block.replace('avery', PERSON).replace('cedar-shop', WORKSPACE) for block in found]


class FreshInstall(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.user = self.root / 'user'
        self.user.mkdir()
        stub = self.root / 'launchctl'
        stub.write_text('#!/bin/sh\necho "$@" >> "%s"\n' % (self.root / 'launchctl.log'))
        stub.chmod(0o755)
        # A clean Mac: system Python, no Foxrun variables, no runtime settings.
        self.env = dict(HOME=str(self.user), PATH='/usr/bin:/bin:/usr/sbin:/sbin', LANG='en_US.UTF-8',
                        TMPDIR=str(self.root), FOXRUN_LAUNCHCTL=str(stub))
        self.home = self.user / '.foxrun'
        self.portfolio = self.user / 'foxrun'

    def shell(self, script, cwd, stdin=None):
        result = subprocess.run(['/bin/sh', '-ec', script], cwd=str(cwd), env=self.env,
                                input=stdin, text=True, capture_output=True, timeout=300)
        self.assertEqual(0, result.returncode, script + '\n' + result.stdout[-3000:] + result.stderr[-3000:])
        return result

    def merge_printed_hooks(self, output):
        """Merge each JSON block install prints into the settings file it names, as GUIDE.md says."""
        decoder, paths = json.JSONDecoder(), []
        for match in re.finditer(r'Add these exact entries to (\S+) \(merge with existing hooks\):\n', output):
            entries, _ = decoder.raw_decode(output, match.end())
            path = Path(match.group(1))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(entries, indent=2) + '\n')
            paths.append(path)
        self.assertEqual({'settings.json', 'hooks.json'}, {path.name for path in paths})
        return paths

    def test_trial_install_writes_no_skill_into_the_real_home(self):
        install = blocks('INSTALL.md', '## Three commands')[0].splitlines()[0]
        trial = self.root / 'trial'
        self.shell(install + ' --runtime-home "%s"' % trial, TREE)
        self.assertFalse((self.user / '.agents').exists())
        self.assertTrue((trial / 'agents/skills/thread/SKILL.md').is_file())

    def test_connect_hooks_after_an_install_without_hookup(self):
        # The easy routes install with no --hookup. INSTALL.md's Connect hooks command connects them, once.
        install = blocks('INSTALL.md', '## Three commands')[0].splitlines()[0]
        self.assertNotIn('--hookup', install)
        self.shell(install, TREE)
        connect, = blocks('INSTALL.md', '## Connect hooks')
        claude, codex = self.user / '.claude/settings.json', self.user / '.codex/hooks.json'
        self.assertFalse(claude.exists() or codex.exists())
        output = self.shell(connect, TREE).stdout
        self.assertIn('Claude: connected 4 hooks', output)
        self.assertIn('Codex: connected 4 hooks', output)
        for settings in (claude, codex):
            hooks = json.loads(settings.read_text())['hooks']
            self.assertEqual({'SessionStart', 'PreCompact', 'SessionEnd'}, set(hooks))
            self.assertIn(str(self.home / 'hooks'), json.dumps(hooks))
        saved = (claude.read_bytes(), codex.read_bytes())
        self.assertIn('Nothing changed.', self.shell(connect, TREE).stdout)
        self.assertEqual(saved, (claude.read_bytes(), codex.read_bytes()))
        # The session-start hook it connected prints the start page.
        folder = self.portfolio / WORKSPACE
        start = json.loads(claude.read_text())['hooks']['SessionStart'][0]['hooks'][0]['command']
        payload = dict(session_id='fresh-hookup', cwd=str(folder), hook_event_name='SessionStart', source='startup')
        result = self.shell(start, folder, json.dumps(payload))
        self.assertIn('Person: ' + PERSON, json.loads(result.stdout)['hookSpecificOutput']['additionalContext'])

    def test_new_person_install_first_task_and_first_session(self):
        # INSTALL.md: the three commands, run from the product folder.
        install, doctor, start = (line for line in blocks('INSTALL.md', '## Three commands')[0].splitlines() if line)
        output = self.shell(install, TREE).stdout
        self.assertIn('Made: Foxrun', output)
        self.assertTrue(self.shell(doctor, TREE).stdout.rstrip().endswith('Doctor: 0 failed'))
        page = self.shell(start, TREE).stdout
        self.assertIn('Person: ' + PERSON, page)
        self.assertIn('Workspace: ' + WORKSPACE, page)
        # T260: the lessons table ships empty; the start page still shows its Lessons part.
        self.assertIn('## Lessons\n0 active lessons for every agent in ' + WORKSPACE, page)
        # The nightly job file renders and launchctl (the stub) loads it.
        plist = self.user / 'Library/LaunchAgents/com.foxrun.session-nightly.plist'
        subprocess.run(['/usr/bin/plutil', '-lint', str(plist)], check=True, capture_output=True)
        self.assertIn('bootstrap', (self.root / 'launchctl.log').read_text())
        watcher = self.user / 'Library/LaunchAgents/com.foxrun.session-nightly-watchdog.plist'
        subprocess.run(['/usr/bin/plutil', '-lint', str(watcher)], check=True, capture_output=True)
        self.assertIn('com.foxrun.session-nightly-watchdog.plist', (self.root / 'launchctl.log').read_text())
        # The pages a new person reads in the product folder match the pages install builds from the rows.
        for name in ('INSTALL.md', 'GUIDE.md'):
            self.assertEqual((TREE / name).read_text(), (self.home / name).read_text(), name)
        self.assertIn('--no-schedule', (TREE / 'GUIDE.md').read_text())

        # Decisions: optional readers never enter a fresh home; state starts empty.
        self.assertTrue((self.home / 'state').is_dir())
        self.assertEqual([], list((self.home / 'state').iterdir()))
        with (self.home / 'base/made-at-install.tsv').open(newline='') as stream:
            self.assertIn({'path': 'state', 'kind': 'folder'}, list(csv.DictReader(stream, delimiter='\t')))
        with (self.home / 'base/product-manifest.tsv').open(newline='') as stream:
            shipped = {row['path'] for row in csv.DictReader(stream, delimiter='\t')}
        for script, page in [('ig-read', 'ig-read'), ('tweet-read', 'tweet-read'), ('browser-humanize.js', 'browser-humanize')]:
            self.assertFalse((self.home / 'tools/bin' / script).exists())
            self.assertNotIn('tools/bin/' + script, shipped)
            self.assertIn('tools/cli/' + page + '.md', shipped)
            self.assertTrue((self.home / 'tools/cli' / (page + '.md')).is_file())
        addons = self.shell('python3 "$HOME/.foxrun/foxrun.py" addons', TREE).stdout
        for name in ('ig-read', 'tweet-read', 'browser-humanize'):
            self.assertIn(name + ':', addons)
        # Run the installed CLI with no external tool on PATH. Only HTTP is a fixture.
        # This checks the actual reader and writer, without a network or a provider key.
        html = '<html><head><title>Fresh article</title></head><body><p>Exact article &amp; words.</p><script>Hidden code</script></body></html>'
        script = """import json, runpy, sys
from pathlib import Path
sys.path.insert(0, str(Path.home() / '.foxrun/capture'))
from readers import common
common.http = lambda url: (HTML.encode(), url, {'Content-Type': 'text/html'})
sys.argv = ['capture-read', 'https://example.org/article', '--out', str(Path.home() / 'reader-output')]
runpy.run_path(str(Path.home() / '.foxrun/capture/capture-read'), run_name='__main__')
""".replace('HTML.encode()', repr(html) + '.encode()')
        probe = self.root / 'read-link.py'
        probe.write_text(script)
        result = self.shell('python3 ' + str(probe), TREE)
        data = json.loads(result.stdout)
        self.assertEqual('ok', data['status'])
        self.assertEqual('html', data['reader'])
        self.assertEqual('Fresh article', data['title'])
        self.assertEqual('Exact article & words.', data['text'])
        # Follow capture's documented workspace settings before saving.
        self.env.update(CAPTURE_ROOT=str(self.portfolio / 'atlas/raw'),
                        CAPTURE_STORE=str(self.home / 'data.db'),
                        CAPTURE_READER_STATE=str(self.root / 'reader-state'))
        reader = self.root / 'reader.json'
        reader.write_text(result.stdout)
        self.shell('python3 "$HOME/.foxrun/capture/capture-write" ' + str(reader), self.portfolio / WORKSPACE)
        self.shell('python3 "$HOME/.foxrun/capture/capture-check"', self.portfolio / WORKSPACE)
        with sqlite3.connect(str(self.home / 'data.db')) as db:
            self.assertEqual(1, db.execute('SELECT count(*) FROM captures').fetchone()[0])

        # The day-one skills are on disk.
        # T245: the seat boots, the shelf skills, and every product skill folder except a retired one.
        seats = {'adviser', 'architect', 'chief', 'keeper', 'scout', 'skillwright', 'toolsmith'}
        shelf = {p.name for p in (TREE / 'skills').iterdir() if p.is_dir()}
        product = {p.name for p in (TREE / 'skillwright/skills').iterdir() if (p / 'SKILL.md').is_file()} - {'to-tickets'}
        self.assertEqual(sorted(seats | shelf | product), sorted(path.name for path in (self.home / 'skills').iterdir()))
        route = self.shell('python3 "$HOME/.foxrun/skills/orchestrate/bin/orchestrate" resolve --from codex --want grill --task "Ask me"', TREE).stdout
        self.assertEqual(json.loads(route)['status'], 'unavailable')
        capabilities = (self.home / 'tools/CAPABILITIES.md').read_text()
        self.assertIn('## Contents', capabilities)
        self.assertIn('## data & docs', capabilities)
        self.assertIn('| defuddle | cli | Add-on: web page to article text | [defuddle](cli/defuddle.md) |', capabilities)
        self.assertIn('[agent-secret-read](cli/agent-secret-read.md)', capabilities)
        self.assertIn('None. Every row in the catalog has its page.', capabilities)
        # A synthetic forbidden-person marker and the host account name stand in for the source owner.
        account = re.split(r'[ ._-]+', pwd.getpwuid(os.getuid()).pw_name)[0]
        for private in ('Wren Example', account):
            if len(private) > 2:
                self.assertNotIn(private.lower(), capabilities.lower())

        # GUIDE.md: make the first task; the start page then shows it.
        result = self.shell(blocks('GUIDE.md', '## Make your first task')[1], TREE).stdout
        task = result.splitlines()[0]
        self.assertRegex(task, r'^T\d+$')
        self.assertIn('Check the first delivery', result)
        with sqlite3.connect(str(self.home / 'data.db')) as db:
            self.assertEqual(('Check the first delivery', 'todo'),
                             db.execute('SELECT title,status FROM tasks WHERE id=?', (task,)).fetchone())

        # GUIDE.md: connect the runtime; pre-compaction now writes a handoff through the shipped helper.
        folder = self.portfolio / WORKSPACE
        for settings in self.merge_printed_hooks(output):
            runtime = 'claude' if settings.name == 'settings.json' else 'codex'
            session = 'fresh-' + runtime
            hooks = json.loads(settings.read_text())['hooks']
            transcript = self.root / (session + '.jsonl')  # the runtime names it after the session
            transcript.write_text('{}\n')
            for event in ('SessionStart', 'PreCompact', 'SessionEnd'):
                for group in hooks[event]:
                    for handler in group['hooks']:
                        payload = dict(session_id=session, cwd=str(folder), hook_event_name=event, source='startup',
                                       trigger='manual', transcript_path=str(transcript), reason='exit')
                        result = self.shell(handler['command'], folder, json.dumps(payload))
                        if event == 'PreCompact' and result.stderr:
                            match = re.fullmatch(r'handoff-precompact: wrote (.+)\n', result.stderr)
                            self.assertIsNotNone(match, result.stderr)
                            note = Path(match.group(1))
                            self.assertEqual(folder / 'history/handoffs', note.parent)
                            self.assertTrue(note.is_file())
                            self.assertIn('workspace: ' + WORKSPACE, note.read_text())
                        else:
                            self.assertEqual('', result.stderr, runtime + ' ' + event + ': ' + handler['command'])
                        if event == 'SessionStart' and result.stdout:
                            context = json.loads(result.stdout)['hookSpecificOutput']['additionalContext']
                            self.assertTrue('Person: ' + PERSON in context or 'Foxrun rules' in context, context[:200])
            # The session is logged as a run, and the end hook closes it.
            with sqlite3.connect(str(self.home / 'data.db')) as db:
                rows = db.execute('SELECT ended_at FROM runs WHERE "session"=?', (session,)).fetchall()
            self.assertEqual(1, len(rows), runtime)
            self.assertIsNotNone(rows[0][0], runtime)
        rules = self.shell('python3 "$HOME/.foxrun/hooks/start-rules.py" 1 </dev/null', folder).stdout
        self.assertIn('agents/soul.md', rules)
        self.assertIn('AGENTS.md', rules)
        # The workspace contracts an agent reads first link only to things that exist.
        for name in ('AGENTS.md', 'RESOLVER.md'):
            for link in re.findall(r'\[\[(' + WORKSPACE + r'/[^\]|]+)', (folder / name).read_text()):
                target = self.portfolio / link
                self.assertTrue(target.exists() or target.with_name(target.name + '.md').exists(), name + ': ' + link)
        # The start page says to read RESOLVER.md first; its lookup command runs.
        command = re.search(r'`(python3 \S+/lookup\.py) <name-or-path>', (folder / 'RESOLVER.md').read_text()).group(1)
        self.assertIn('tasks', self.shell(command + ' tasks --db "$HOME/.foxrun/data.db"', folder).stdout)
        self.assertIn('what the person ruled', self.shell('python3 "$HOME/.foxrun/foxrun.py" --help', folder).stdout)


class CleanCopy(unittest.TestCase):
    def test_every_install_input_is_in_git(self):
        """A copy made from git, not this folder, must hold every shipped file and starter (T595)."""
        def tracked(folder, prefix):
            result = subprocess.run(['git', '-C', str(folder), 'ls-files'], capture_output=True, text=True)
            if result.returncode:
                self.skipTest('no git checkout at ' + str(folder))
            return {prefix + name for name in result.stdout.splitlines()}
        names = tracked(TREE, '') | tracked(TREE / 'agents', 'agents/')
        with (TREE / 'product-manifest.tsv').open(newline='') as stream:
            shipped = {row['path'] for row in csv.DictReader(stream, delimiter='\t')}
        spec = importlib.util.spec_from_file_location('fresh_install_installer', str(TREE / 'install.py'))
        installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(installer)
        self.assertEqual([], sorted((shipped | set(installer.STARTERS)) - names))


if __name__ == '__main__':
    unittest.main()
