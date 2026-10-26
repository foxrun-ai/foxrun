#!/usr/bin/env python3
"""Tests for the workers of work/flow.py: graph order, the repair loop, the gate, the worker start, and the tracker.

The launcher is a stub: a fake orchestrate in the test home, and fake claude and codex programs on PATH.
No real runtime starts. The last test installs a fresh home and runs a shipped starter flow end to end,
with the installed orchestrate and a fake claude.

Run from the system home: python3 -m unittest work.tests.test_flow_workers
"""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import shlex
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
PYTHON = '/usr/bin/python3' if Path('/usr/bin/python3').is_file() else 'python3'
NEEDED = ('work/flow.py', 'base/paths.py', 'base/person.py', 'base/simple_yaml.py',
          'base/agent_catalog.py', 'config/models.yaml')
STARTERS = ROOT / 'skillwright/workflows'
STARTER_NAMES = ('review', 'research')  # Approval 470: the two product starters.
PERSONAL_VOTE = ROOT / 'work/tests/fixtures/personal-workflows/vote.yaml'

spec = importlib.util.spec_from_file_location('flow_under_test', ROOT / 'work/flow.py')
FLOW = importlib.util.module_from_spec(spec)
spec.loader.exec_module(FLOW)

# The fake orchestrate: the same route shapes the real resolver gives a codex caller.
ORCHESTRATE = r'''#!/usr/bin/env python3
import json, os, shlex, sys
args = sys.argv[1:]
value = lambda flag: args[args.index(flag) + 1]
with open(os.environ['FAKE_LOG'], 'a') as log:
    log.write(json.dumps({'program': 'orchestrate', 'to': value('--to'), 'want': value('--want'), 'cwd': value('--cwd')}) + '\n')
to, want, cwd, task = value('--to'), value('--want'), value('--cwd'), value('--task')
if to == 'claude':
    tools = 'Read,Glob,Grep' if want == 'quick' else 'Read,Edit,Write,Bash'
    command = 'cd ' + shlex.quote(cwd) + ' && claude -p ' + shlex.quote(task) + ' --output-format json --allowedTools ' + tools
else:
    command = 'codex exec -s ' + ('read-only' if want == 'quick' else 'workspace-write') + ' -C ' + shlex.quote(cwd) + \
              ' --json -o ' + shlex.quote(value('--run-dir') + '/result.md') + ' ' + shlex.quote(task)
print(json.dumps({'status': 'resolved', 'mode': 'one-shot', 'opens_window': False, 'command': command}))
'''
# The fake runtimes. A verdict brief takes the next word of FAKE_VERDICTS (pass when none is left).
RUNTIME = r'''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
name = Path(sys.argv[0]).name
task = args[args.index('-p') + 1] if name == 'claude' else args[-1]
step = [line for line in task.splitlines() if line.startswith('Step: ')][0].split()[1]
with open(os.environ['FAKE_LOG'], 'a') as log:
    log.write(json.dumps({'program': name, 'step': step, 'argv': args[:-1] if name == 'codex' else
                          [a for a in args if a != task], 'cwd': os.getcwd()}) + '\n')
if os.environ.get('FAKE_FAIL') == step:
    sys.exit(3)
if 'verdict: pass, or verdict: fail' in task:
    state = Path(os.environ['FAKE_LOG']).with_name('verdicts-used')
    used = int(state.read_text()) if state.exists() else 0
    words = [w for w in os.environ.get('FAKE_VERDICTS', '').split(',') if w]
    state.write_text(str(used + 1))
    reply = 'verdict: ' + (words[used] if used < len(words) else 'pass') + '\nFindings for ' + step + '.'
else:
    reply = 'The result of ' + step + '.'
if name == 'claude':
    print(json.dumps({'type': 'result', 'is_error': False, 'result': reply, 'session_id': 'fake'}))
else:
    Path(args[args.index('-o') + 1]).write_text(reply + '\n')
'''
# The fake tracker writer: it records each call and answers like work/work.py.
WORK = r'''import json, os, sys
with open(os.environ['FAKE_LOG'], 'a') as log:
    log.write(json.dumps({'program': 'work.py', 'argv': sys.argv[1:]}) + '\n')
print('R-1-' + sys.argv[-1] if 'run-start' in sys.argv else 'ok ' + sys.argv[-2] + ' ' + sys.argv[-1])
'''
GATED = ('version: 1\nflow: gated\npurpose: "Draft, then the person says yes, then a second draft."\n'
         'members:\n  writer: {what: "Writes.", runtime: claude}\ngraph:\n'
         '  draft:\n    member: writer\n    gate: send\n    done_when: {file: draft.md}\n'
         '  final:\n    member: writer\n    needs: [draft]\n    done_when: {file: final.md}\n')
MIXED = ('version: 1\nflow: mixed\npurpose: "One worker on codex, one step by hand."\n'
         'members:\n  coder: {what: "Codes.", runtime: codex, model: test-model, effort: low, access: write}\n'
         '  person: {what: "The lead, by hand."}\ngraph:\n'
         '  code:\n    member: coder\n    done_when: {file: code.md}\n'
         '  check:\n    member: person\n    needs: [code]\n    done_when: {file: check.md}\n')


class Home(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='flow-workers-')
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name).resolve()
        self.home, self.portfolio, self.bin = root / 'system', root / 'portfolio', root / 'bin'
        for name in NEEDED:
            (self.home / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, self.home / name)
        for folder in ('config', 'runs', 'agents', 'skills', 'skillwright/skills', 'skillwright/workflows'):
            (self.home / folder).mkdir(parents=True, exist_ok=True)    # small-talk/skills is not made: a missing place is read as empty
        for name in STARTER_NAMES:
            source = STARTERS / (name + '.yaml')
            shutil.copyfile(source, self.home / 'skillwright/workflows' / source.name)
        if PERSONAL_VOTE.is_file():
            shutil.copyfile(PERSONAL_VOTE, self.home / 'skillwright/workflows/vote.yaml')
        for seat in ('toolsmith', 'keeper', 'architect', 'skillwright'):
            (self.home / 'agents' / (seat + '.md')).write_text('# ' + seat + '\n')
        for skill in ('log', 'runtime-session-search'):
            folder = self.home / 'skills' / skill
            folder.mkdir()
            (folder / 'SKILL.md').write_text('# ' + skill + '\n')
        (self.portfolio / 'cedar-shop/workflows').mkdir(parents=True)
        (self.home / 'skillwright/workflows/.product').mkdir()
        (self.home / 'config/person.json').write_text(json.dumps({'name': 'avery'}))
        (self.portfolio / 'cedar-shop/skills').mkdir(parents=True)
        self.bin.mkdir()
        for name in ('claude', 'codex'):
            (self.bin / name).write_text(RUNTIME)
            (self.bin / name).chmod(0o755)
        self.log = root / 'calls.jsonl'
        self.env = {key: value for key, value in os.environ.items() if not key.startswith(('FOXRUN_', 'FAKE_'))}
        self.env.update(FOXRUN_HOME=str(self.home), FOXRUN_PORTFOLIO=str(self.portfolio), PYTHONDONTWRITEBYTECODE='1',
                        PATH=str(self.bin) + os.pathsep + self.env.get('PATH', '/usr/bin:/bin'), FAKE_LOG=str(self.log))

    def launcher(self):
        target = self.home / 'skills/orchestrate/bin/orchestrate'
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(ORCHESTRATE)
        target.chmod(0o755)

    def flow(self, *args, expected=0, **more):
        env = dict(self.env, **more)
        result = subprocess.run([PYTHON, '-B', str(self.home / 'work/flow.py')] + list(args), cwd=str(self.home), env=env,
                                text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.assertEqual(result.returncode, expected, result.stdout)
        return result.stdout

    def worker_calls(self):
        return [row for row in self.calls() if row['program'] in ('claude', 'codex')]

    def calls(self, program=None):
        rows = [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []
        return [row for row in rows if program is None or row['program'] == program]

    def run_folder(self):
        (folder,) = [p for p in (self.home / 'runs').iterdir() if (p / 'runner/run.yaml').is_file()]
        return folder

    def write_flow(self, name, text):
        (self.home / 'skillwright/workflows' / (name + '.yaml')).write_text(text)


class GraphTests(Home):
    def test_order_puts_each_step_after_every_step_it_needs(self):
        graph = {'merge': {'needs': ['a', 'b']}, 'a': {'needs': []}, 'b': {'needs': ['a']}, 'c': {'needs': ['merge']}}
        order = FLOW.order(graph)
        for step, body in graph.items():
            for need in body['needs']:
                self.assertLess(order.index(need), order.index(step))
        self.assertEqual(FLOW.ancestors(graph, 'c'), ['merge', 'a', 'b'])
        self.assertEqual(FLOW.ancestors(graph, 'a'), [])

    def test_research_starts_its_three_researchers_together_and_the_merge_after_them(self):
        self.launcher()
        output = self.flow('run', 'research', '--input', 'question=Which tool?')
        self.assertIn('State: done', output)
        steps = [row['step'] for row in self.worker_calls()]
        self.assertEqual(sorted(steps[:3]), ['find-doubt', 'find-practice', 'find-sources'])
        self.assertEqual(steps[3:], ['merge'])
        folder = self.run_folder()
        brief = (folder / 'runner/workers/merge-1/brief.md').read_text()
        for name in ('sources.md', 'practice.md', 'doubt.md'):
            self.assertIn(str(folder / name), brief)
        alone = (folder / 'runner/workers/find-doubt-1/brief.md').read_text()
        self.assertNotIn('sources.md', alone)          # a researcher reads no other finding
        self.assertEqual((folder / 'answer.md').read_text(), 'The result of merge.\n')


class LoopTests(Home):
    def test_review_repairs_until_the_reader_passes(self):
        self.launcher()
        output = self.flow('run', 'review', '--input', 'job=Write a page', FAKE_VERDICTS='fail,fail,pass')
        self.assertIn('State: done', output)
        self.assertEqual([row['step'] for row in self.worker_calls()], ['build', 'routine-read', 'recheck', 'read'] * 3)
        folder = self.run_folder()
        self.assertTrue((folder / 'runner/attempts/1/read.md').is_file())
        self.assertTrue((folder / 'runner/attempts/2/read.md').is_file())
        self.assertIn('repair round', (folder / 'runner/workers/build-3/brief.md').read_text())
        self.assertIn(str(folder / 'runner/attempts/2/read.md'), (folder / 'runner/workers/build-3/brief.md').read_text())
        self.assertEqual((folder / 'read.md').read_text().splitlines()[0], 'verdict: pass')

    def test_review_stops_as_blocked_when_no_repair_round_is_left(self):
        self.launcher()
        output = self.flow('run', 'review', '--input', 'job=Write a page', FAKE_VERDICTS='fail,fail,fail,fail', expected=1)
        self.assertIn('State: blocked', output)
        self.assertIn('no repair round is left', output)
        self.assertEqual(len(self.worker_calls()), 16)          # four checked steps, four times: three repairs at most


class GateTests(Home):
    def test_a_worker_result_waits_for_the_yes_and_nothing_after_it_starts(self):
        self.launcher()
        self.write_flow('gated', GATED)
        output = self.flow('run', 'gated')
        self.assertIn('State: waits for avery', output)
        self.assertEqual([row['step'] for row in self.calls('claude')], ['draft'])
        folder = self.run_folder()
        self.assertFalse((folder / 'final.md').exists())
        self.flow('run', '--resume', folder.name)                 # a resume with no yes starts nothing
        self.assertEqual(len(self.calls('claude')), 1)
        output = self.flow('run', '--resume', folder.name, '--yes', 'draft', '--words', 'Yes, send it.')
        self.assertIn('State: done', output)
        self.assertEqual([row['step'] for row in self.calls('claude')], ['draft', 'final'])

    @unittest.skipUnless(PERSONAL_VOTE.is_file(), 'Personal vote fixture is build-only.')
    def test_vote_reaches_the_ruling_gate_and_a_no_ends_it(self):
        self.launcher()
        output = self.flow('run', 'vote', '--input', 'question=One list or two?', FAKE_VERDICTS='fail,pass')
        self.assertIn('State: waits for avery', output)
        self.assertIn('result (ruling gate)', output)
        steps = [row['step'] for row in self.calls('claude')]
        self.assertEqual(sorted(steps[:3]), ['answer-a', 'answer-b', 'answer-c'])
        self.assertEqual(steps.count('compare'), 2)               # the split point ran one repair round
        self.assertEqual(steps.count('answer-a'), 1)               # the first answers stay
        folder = self.run_folder()
        self.assertEqual(self.flow('run', '--resume', folder.name, '--no', 'result', '--words', 'No.', expected=1).count('State: refused'), 1)


class WorkerTests(Home):
    def test_each_worker_gets_its_route_model_effort_and_access(self):
        self.launcher()
        self.write_flow('mixed', MIXED)
        output = self.flow('run', 'mixed', '--workspace', 'cedar-shop')
        self.assertIn('NEXT  check', output)                       # a member with no runtime is done by hand
        (route,) = self.calls('orchestrate')
        self.assertEqual((route['to'], route['want'], route['cwd']), ('codex', 'fix', str(self.portfolio / 'cedar-shop')))
        (codex,) = self.calls('codex')
        self.assertEqual(codex['argv'][:5], ['exec', '-m', 'test-model', '-c', 'model_reasoning_effort=low'])
        self.assertIn('workspace-write', codex['argv'])
        self.assertEqual(codex['cwd'], str(self.portfolio / 'cedar-shop'))
        folder = self.run_folder()
        self.assertEqual(json.loads((folder / 'runner/workers/code-1/argv.json').read_text())[codex['argv'].index('-o') + 2],
                         str(folder / 'runner/workers/code-1/reply.md'))
        self.assertEqual((folder / 'code.md').read_text(), 'The result of code.\n')

    def test_a_read_member_gets_a_read_only_route(self):
        self.launcher()
        self.flow('run', 'research', '--input', 'question=q')
        routes = self.calls('orchestrate')
        self.assertEqual([row['want'] for row in routes].count('quick'), 3)
        self.assertEqual([row['want'] for row in routes].count('fix'), 1)
        self.assertTrue(all('Read,Glob,Grep' in row['argv'] for row in self.calls('claude')))
        codex = self.calls('codex')
        self.assertEqual(sum('read-only' in row['argv'] for row in codex), 2)
        self.assertEqual(sum('workspace-write' in row['argv'] for row in codex), 1)

    def test_a_file_that_is_there_is_never_overwritten_and_never_started(self):
        self.launcher()
        self.write_flow('mixed', MIXED)
        self.flow('run', 'mixed', '--no-workers')
        folder = self.run_folder()
        self.assertEqual(self.calls(), [])                          # --no-workers starts nobody
        (folder / 'code.md').write_text('Written by hand.\n')
        self.flow('run', '--resume', folder.name)
        self.assertEqual(self.calls('codex'), [])
        self.assertEqual((folder / 'code.md').read_text(), 'Written by hand.\n')

    def test_a_worker_that_fails_gives_no_result_and_is_started_again_only_by_a_resume(self):
        self.launcher()
        self.write_flow('gated', GATED)
        output = self.flow('run', 'gated', FAKE_FAIL='draft')
        self.assertIn('worker  started, and gave no result', output)
        folder = self.run_folder()
        self.assertFalse((folder / 'draft.md').exists())
        self.assertEqual(json.loads((folder / 'runner/workers/draft-1/end.json').read_text())['exit'], 3)
        self.assertEqual(len(self.calls('claude')), 1)
        self.flow('run', '--resume', folder.name)
        self.assertEqual(len(self.calls('claude')), 2)
        self.assertTrue((folder / 'draft.md').is_file())

    def test_with_no_launcher_the_step_is_done_by_hand(self):
        output = self.flow('run', 'review', '--input', 'job=x')
        self.assertIn('NEXT  build', output)
        self.assertIn('worker  not started: no launcher at ' + str(self.home / 'skills/orchestrate/bin/orchestrate'), output)
        self.assertEqual(self.calls(), [])

    def test_with_member_puts_model_and_effort_into_each_runtime(self):
        folder = Path('/tmp/run')
        member = {'model': 'm1', 'effort': 'high'}
        self.assertEqual(FLOW.with_member(['claude', '-p', 'x', '--allowedTools', 'Read'], member, folder, folder),
                         ['claude', '--model', 'm1', '--effort', 'high', '-p', 'x', '--allowedTools', 'Read'])
        self.assertEqual(FLOW.with_member(['claude', '-p', 'x'], {'model': None, 'effort': None}, folder, Path('/tmp/ws')),
                         ['claude', '--add-dir', '/tmp/run', '-p', 'x'])
        self.assertEqual(FLOW.with_member(['codex', 'exec', '-m', 'old', '-c', 'model_reasoning_effort=low', 'x'], member, folder, folder),
                         ['codex', 'exec', '-m', 'm1', '-c', 'model_reasoning_effort=high', 'x'])
        self.assertEqual(FLOW.with_member(['hermes', '-z', 'x'], member, folder, folder), ['hermes', '-m', 'm1', '-z', 'x'])

    def test_routed_refuses_shell_routes_and_windows(self):
        work = Path('/tmp/w')
        self.assertEqual(FLOW.routed({'status': 'resolved', 'mode': 'one-shot', 'command': 'cd /tmp && claude -p hi'}, '/tmp', work),
                         ['claude', '-p', 'hi'])
        for route in ({'status': 'refused', 'mode': 'one-shot', 'command': 'claude -p x'},
                      {'status': 'resolved', 'mode': 'hosted', 'command': 'claude -p x'},
                      {'status': 'resolved', 'mode': 'one-shot', 'command': 'claude -p x | tee y'},
                      {'status': 'resolved', 'mode': 'one-shot', 'command': 'sh -c x'},
                      {'status': 'resolved', 'mode': 'one-shot', 'command': 'cd /elsewhere && claude -p x'}):
            with self.subTest(route=route):
                with self.assertRaises(FLOW.FlowError):
                    FLOW.routed(route, '/tmp', work)


class PlaceTests(Home):
    def test_a_missing_optional_place_is_read_as_empty_and_named(self):
        self.assertFalse((self.home / 'small-talk/skills').exists())
        output = self.flow('status')
        self.assertIn('Places that are not there: 1. Each is read as empty.', output)
        self.assertIn(str(self.home / 'small-talk/skills'), output)
        self.assertIn('review (workflow): valid', output)
        self.flow('run', 'review', '--input', 'job=x', '--dry-run')

    def test_a_plain_file_in_the_runs_folder_is_not_a_run(self):
        (self.home / 'runs/state-markers.json').write_text('{}\n')
        output = self.flow('status')
        self.assertIn('Runs: 0', output)
        self.assertNotIn('NOT READABLE', output)

    def test_a_place_that_can_not_be_listed_still_stops_the_name(self):
        (self.home / 'small-talk').mkdir()
        (self.home / 'small-talk/skills').write_text('a file, not a folder\n')
        self.assertIn('can not be looked up', self.flow('run', 'review', '--input', 'job=x', '--dry-run', expected=2))


class TrackerTests(Home):
    def tracker(self, *tasks):
        (self.home / 'work/work.py').write_text(WORK)
        with sqlite3.connect(str(self.home / 'data.db')) as db:
            db.execute('CREATE TABLE tasks (id TEXT PRIMARY KEY)')
            db.executemany('INSERT INTO tasks VALUES (?)', [(task,) for task in tasks])

    def test_each_worker_step_and_code_step_is_a_run_on_the_task(self):
        self.launcher()
        self.tracker('T9')
        (self.home / 'tools').mkdir()
        (self.home / 'tools/count.py').write_text('print("counted")\n')
        self.write_flow('counted', 'version: 1\nflow: counted\npurpose: "A worker, then code."\n'
                        'members:\n  writer: {what: "Writes.", runtime: claude}\ngraph:\n'
                        '  draft:\n    member: writer\n    done_when: {file: draft.md}\n'
                        '  count:\n    run: [python3, tools/count.py]\n    needs: [draft]\n')
        output = self.flow('run', 'counted', '--task', 'T9')
        self.assertIn('Task: T9', output)
        self.assertIn('State: done', output)
        folder = self.run_folder()
        calls = [row['argv'] for row in self.calls('work.py')]
        self.assertEqual([argv[-2] for argv in calls], ['run-start', 'run-end', 'run-start', 'run-end'])
        for argv in calls:
            self.assertEqual(argv[:4], ['--db', str(self.home / 'data.db'), '--receipt-root', str(self.home)])
        self.assertEqual(calls[0][calls[0].index('--model') + 1:calls[0].index('--model') + 4], ['default', '--runtime', 'claude'])
        self.assertEqual(calls[1][calls[1].index('--proof') + 1], 'runs/' + folder.name + '/draft.md')
        self.assertEqual(calls[1][calls[1].index('--result') + 1], 'pass')
        self.assertEqual(calls[3][calls[3].index('--proof') + 1], 'runs/' + folder.name + '/runner/events.jsonl')
        self.assertEqual(json.loads((folder / 'runner/run.yaml').read_text())['task'], 'T9')

    def test_a_workspace_with_its_own_tracker_records_the_runs_there(self):
        self.launcher()
        self.tracker('T9')     # the system tracker has T9 too: the workspace one must win
        shop = self.portfolio / 'cedar-shop'
        with sqlite3.connect(str(shop / 'data.db')) as db:
            db.execute('CREATE TABLE tasks (id TEXT PRIMARY KEY)')
            db.execute("INSERT INTO tasks VALUES ('T9')")
        output = self.flow('run', 'review', '--input', 'job=x', '--workspace', 'cedar-shop', '--task', 'T9')
        self.assertIn('State: done', output)
        self.assertEqual([p for p in (self.home / 'runs').iterdir()], [])
        (folder,) = [p for p in (shop / 'history/runs').iterdir() if (p / 'runner/run.yaml').is_file()]
        calls = [row['argv'] for row in self.calls('work.py')]
        self.assertEqual([argv[-2] for argv in calls], ['run-start', 'run-end'] * 4)
        for argv in calls:
            self.assertEqual(argv[:4], ['--db', str(shop / 'data.db'), '--receipt-root', str(shop)])
        for call, page in zip(calls[1::2], ('build.md', 'routine.md', 'recheck.md', 'read.md')):
            self.assertEqual(call[call.index('--proof') + 1], 'history/runs/' + folder.name + '/' + page)
        self.assertEqual(calls[1][calls[1].index('--proof') + 1], 'history/runs/' + folder.name + '/build.md')
        # The run is found by its name alone, listed by status, and its name is not given twice.
        self.assertIn('Nothing was changed', self.flow('run', '--resume', folder.name))
        listed = self.flow('status')
        self.assertIn(folder.name + ': done  (in ' + str(shop / 'history/runs') + ')', listed)
        again = self.flow('run', 'review', '--input', 'job=y')
        self.assertIn('Run: ' + folder.name + '-2', again)
        (shop / 'history/runs' / (folder.name + '-2')).mkdir()
        self.assertIn('two folders have the run name', self.flow('run', '--resume', folder.name + '-2', expected=2))

    def test_a_task_that_is_not_in_the_tracker_starts_no_run(self):
        self.tracker('T9')
        self.assertIn('no such task', self.flow('run', 'review', '--input', 'job=x', '--task', 'T404', expected=2))
        self.assertEqual(list((self.home / 'runs').iterdir()), [])
        self.assertIn('go with a new run', self.flow('run', '--resume', 'x', '--task', 'T9', expected=2))


class FreshInstallTests(unittest.TestCase):
    # The installer is source-only: a live home has no install.py (T671 base study, recheck 2 T742).
    @unittest.skipUnless((ROOT / 'install.py').exists(), 'install.py ships in the source tree only')
    def test_a_fresh_install_runs_a_starter_flow_end_to_end_with_one_command(self):
        with tempfile.TemporaryDirectory(prefix='flow-fresh-') as name:
            root = Path(name).resolve()
            user, home, portfolio, bin_ = root / 'user', root / 'system', root / 'portfolio', root / 'bin'
            user.mkdir()
            bin_.mkdir()
            env = {key: value for key, value in os.environ.items() if not key.startswith(('FOXRUN_', 'FAKE_', 'PYTHON'))}
            env.update(HOME=str(user), PYTHONDONTWRITEBYTECODE='1')
            stub = root / 'launchctl'
            stub.write_text('#!/bin/sh\n')
            stub.chmod(0o755)
            env['FOXRUN_LAUNCHCTL'] = str(stub)
            done = subprocess.run([PYTHON, '-B', str(ROOT / 'install.py'), '--yes', '--no-schedule', '--home', str(home),
                                   '--portfolio', str(portfolio)], env=env, text=True, capture_output=True, cwd=str(ROOT))
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
            for starter in ('review', 'research'):
                self.assertTrue((home / 'skillwright/workflows' / (starter + '.yaml')).is_file(), starter)
                self.assertTrue((home / 'skillwright/workflows' / (starter + '.md')).is_file(), starter)
            self.assertFalse((home / 'skillwright/workflows/vote.yaml').exists())
            self.assertFalse((home / 'skillwright/workflows/vote.md').exists())
            # Both installed runtimes are local stubs. No model or session starts.
            resolver = home / 'skills/orchestrate/bin/orchestrate'
            self.assertTrue(os.access(str(resolver), os.X_OK), 'install puts orchestrate on the shelf')
            for part in ('SKILL.md', 'bin/orchestrate'):
                self.assertEqual((home / 'skills/orchestrate' / part).read_bytes(),
                                 (ROOT / 'skillwright/skills/orchestrate' / part).read_bytes(), part)
            for runtime in ('claude', 'codex'):
                (bin_ / runtime).write_text(RUNTIME)
                (bin_ / runtime).chmod(0o755)
            env.update(FOXRUN_HOME=str(home), FOXRUN_PORTFOLIO=str(portfolio), FAKE_LOG=str(root / 'calls.jsonl'),
                       FAKE_VERDICTS='fail,pass', PATH=str(bin_) + os.pathsep + env.get('PATH', '/usr/bin:/bin'))
            made = subprocess.run([PYTHON, '-B', str(home / 'work/work.py'), '--db', str(home / 'data.db'), '--receipt-root', str(home),
                                   '--by', 'avery', 'create', '--title', 'Write the returns page', '--problem', 'No returns page.',
                                   '--acceptance', 'The page passes a review.', '--job-when', 'a buyer asks about returns',
                                   '--job-want', 'one page', '--job-so', 'they know the rule', '--body', 'One page.',
                                   '--context', 'None yet.', '--where', str(home / 'skillwright/workflows')],
                                  env=env, text=True, capture_output=True)
            with sqlite3.connect(str(home / 'data.db')) as db:
                task = db.execute('SELECT id FROM tasks ORDER BY rowid DESC LIMIT 1').fetchone()
            self.assertIsNotNone(task, made.stdout + made.stderr)
            task = task[0]
            ran = subprocess.run([PYTHON, '-B', str(home / 'work/flow.py'), 'run', 'review', '--task', task,
                                  '--input', 'job=Write the returns page'], env=env, text=True, capture_output=True, cwd=str(home))
            self.assertEqual(ran.returncode, 0, ran.stdout + ran.stderr)
            self.assertIn('State: done', ran.stdout)
            with sqlite3.connect(str(home / 'data.db')) as db:
                rows = db.execute("SELECT model, runtime, result, evidence FROM runs WHERE subject_id=? ORDER BY started_at", (task,)).fetchall()
            self.assertEqual([(row[1], row[2]) for row in rows], [(runtime, 'pass') for runtime in ['codex', 'codex', 'codex', 'claude'] * 2], ran.stderr)
            self.assertTrue(all(row[3].startswith('runs/') for row in rows))
            (folder,) = [p for p in (home / 'runs').iterdir() if (p / 'runner/run.yaml').is_file()]
            routes = [json.loads((work / 'route.json').read_text()) for work in sorted((folder / 'runner/workers').iterdir())]
            self.assertEqual(len(routes), 8)
            for route in routes:
                self.assertEqual(route['status'], 'resolved')
                command = shlex.split(route['command'])
                if command[0] == 'codex':
                    self.assertEqual(command[:2], ['codex', 'exec'])
                    self.assertEqual(command[command.index('-C') + 1], str(folder))
                else:
                    self.assertEqual(command[:3], ['cd', str(folder), '&&'])
            runtime_calls = [json.loads(line) for line in (root / 'calls.jsonl').read_text().splitlines()]
            self.assertTrue(all(call['cwd'] == str(folder) for call in runtime_calls))
            self.assertEqual([call['program'] for call in [json.loads(line) for line in (root / 'calls.jsonl').read_text().splitlines()]],
                             ['codex', 'codex', 'codex', 'claude'] * 2)
            status = subprocess.run([PYTHON, '-B', str(home / 'work/flow.py'), 'status'], env=env, text=True, capture_output=True)
            self.assertEqual(status.returncode, 0, status.stdout + status.stderr)


if __name__ == '__main__':
    unittest.main()
