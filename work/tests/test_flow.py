#!/usr/bin/env python3
"""Tests for work/flow.py. Each test makes a small home with only the files it needs.

The tests named test_gate_* and test_order_* hold the rules that may never break:
no step passes a gate without a recorded yes, and no result counts before the steps it needs.

Run from the system home: python3 -m unittest work.tests.test_flow
"""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
PYTHON = '/usr/bin/python3' if Path('/usr/bin/python3').is_file() else 'python3'
NEEDED = ('work/flow.py', 'base/paths.py', 'base/person.py', 'base/simple_yaml.py')
# Keep runner examples independent of exported workflow descriptions.
WORKFLOW_FIXTURES = Path(__file__).resolve().parent / 'fixtures/workflows'
NOW = '2026-10-13T12:00:00+00:00'      # a time in the form the runner writes, for a record a test writes by hand
SEATS = ('mercer', 'amazon-operator', 'creative-reviewer', 'creative-strategist', 'ugc-producer', 'designer', 'video-producer')
# Two branches with no line between them: gate, and prepare > change. The reader's refusal probe.
TWO_BRANCHES = ('version: 1\nflow: two-branches\npurpose: "Two branches that do not need each other."\n'
                'members:\n  worker: {seat: mercer}\ngraph:\n'
                '  gate:\n    member: worker\n    gate: production\n    done_when: {file: gate.md}\n'
                '  prepare:\n    member: worker\n    done_when: {file: prepare.md}\n'
                '  change:\n    run: [python3, tools/change.py]\n    needs: [prepare]\n')
# prepare, then a code step. The third reader's probes use it.
PREPARE_CHANGE = ('version: 1\nflow: prepare-change\npurpose: "Prepare, then change."\nmembers:\n  worker: {seat: mercer}\ngraph:\n'
                  '  prepare:\n    member: worker\n    done_when: {file: prepare.md}\n'
                  '  change:\n    run: [python3, tools/{script}]\n    needs: [prepare]\n')
SLOW = ("import os, pathlib, time\nfolder = pathlib.Path(os.environ['FOXRUN_RUN_DIR'])\n"
        "with (folder / 'executions.txt').open('a') as stream:\n    stream.write('executed\\n')\ntime.sleep(1.2)\n")
KILLS_THE_RUNNER = ("import os, pathlib, signal\nfolder = pathlib.Path(os.environ['FOXRUN_RUN_DIR'])\n"
                    "with (folder / 'executions.txt').open('a') as stream:\n    stream.write('executed\\n')\n"
                    "os.kill(os.getppid(), signal.SIGKILL)\n")
CODE_GATE = ('version: 1\nflow: code-gate\npurpose: "Change one thing in production."\ngraph:\n'
             '  publish:\n    run: [python3, tools/change.py]\n    gate: production\n')


class FlowTests(unittest.TestCase):
    def setUp(self):
        parent = os.environ.get('FOXRUN_TEST_ROOT') or None
        self.temp = tempfile.TemporaryDirectory(prefix='flow-home-', dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name).resolve() / 'system'
        self.portfolio = Path(self.temp.name).resolve() / 'portfolio'
        for name in NEEDED:
            (self.home / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, self.home / name)
        for source in sorted(WORKFLOW_FIXTURES.glob('*.yaml')):
            target = self.home / 'skillwright/workflows' / source.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        # A whole home: each of the four shared places is a folder, and each seat the two workflow files name has its seat file.
        for folder in ('config', 'runs', 'agents', 'skills/log', 'skillwright/skills', 'skillwright/workflows', 'small-talk/skills', 'tools'):
            (self.home / folder).mkdir(parents=True, exist_ok=True)
        (self.home / 'config/person.json').write_text(json.dumps({'name': 'avery'}))
        for seat in SEATS:
            (self.home / 'agents' / (seat + '.md')).write_text('# ' + seat + '\n')
        (self.home / 'skills/log/SKILL.md').write_text('# log\n')
        (self.home / 'tools/change.py').write_text(
            "import os, pathlib\npathlib.Path(os.environ['FOXRUN_RUN_DIR'], 'changed').write_text('changed')\n")
        # A whole workspace: it has its skills folder and its team folder.
        (self.portfolio / 'cedar-shop/team').mkdir(parents=True)
        (self.portfolio / 'cedar-shop/skills').mkdir()
        (self.portfolio / 'cedar-shop/workflows').mkdir()
        (self.home / 'skillwright/workflows/.product').mkdir()
        (self.portfolio / 'cedar-shop/team/amazon-operator.md').write_text('# Amazon operator\n')
        self.env = {key: value for key, value in os.environ.items() if not key.startswith('FOXRUN_')}
        self.env.update(FOXRUN_HOME=str(self.home), FOXRUN_PORTFOLIO=str(self.portfolio), PYTHONDONTWRITEBYTECODE='1')

    def flow(self, *args, expected=0):
        result = subprocess.run([PYTHON, '-B', str(self.home / 'work/flow.py')] + list(args), cwd=str(self.home),
                                env=self.env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.assertEqual(result.returncode, expected, result.stdout)
        return result.stdout

    def run_folder(self, ending=''):
        folders = sorted(p for p in (self.home / 'runs').iterdir() if (p / 'runner/run.yaml').is_file() and p.name.endswith(ending))
        self.assertEqual(len(folders), 1)
        return folders[0]

    def write_flow(self, name, text, skill=False):
        file = (self.home / 'skillwright/skills' / name / 'flow.yaml') if skill else \
            (self.home / 'skillwright/workflows' / (name + '.yaml'))
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(text)

    def start_amazon(self):
        output = self.flow('run', 'operate-amazon', '--workspace', 'cedar-shop', '--input', 'listing=B0TEST')
        return self.run_folder(), output

    def step(self, folder, name, text, expected=0):
        """A member writes one result. Then code accepts it."""
        (folder / name).write_text(text)
        return self.flow('run', '--resume', folder.name, expected=expected)

    def to_the_gate(self):
        folder, _ = self.start_amazon()
        self.step(folder, 'audit.md', 'findings\n')
        self.step(folder, 'check.md', 'verdict: pass\ncleared\n')
        output = self.step(folder, 'decide.md', 'One ask: change the title.\n')
        self.assertIn('State: waits for avery', output)
        return folder

    def states(self, folder):
        result = subprocess.run([PYTHON, '-B', str(self.home / 'work/flow.py'), 'status', folder.name, '--json'], cwd=str(self.home), env=self.env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        data = json.loads(result.stdout)
        self.assertEqual(result.returncode, 1 if data['state'] in ('blocked', 'refused') else 0, result.stdout)
        return data['state'], {step: row['state'] for step, row in data['steps'].items()}

    def popen(self, *args):
        return subprocess.Popen([PYTHON, '-B', str(self.home / 'work/flow.py')] + list(args), cwd=str(self.home),
                                env=self.env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

    def prepare_change(self, script='change.py', write=True):
        (self.home / 'tools/slow.py').write_text(SLOW)
        (self.home / 'tools/kill.py').write_text(KILLS_THE_RUNNER)
        self.write_flow('prepare-change', PREPARE_CHANGE.replace('{script}', script))
        self.flow('run', 'prepare-change')
        folder = self.run_folder('prepare-change')
        if write:
            (folder / 'prepare.md').write_text('Ready.\n')
        return folder

    def wait_for(self, file, seconds=8):
        until = time.monotonic() + seconds
        while not file.exists() and time.monotonic() < until:
            time.sleep(0.01)
        self.assertTrue(file.exists(), str(file))

    def record(self, folder, step, decision):
        """The file of a yes or a no. It is a file of the runner: runner/decisions/<step>.<yes|no>.md."""
        (folder / 'runner/decisions').mkdir(exist_ok=True)
        return folder / 'runner/decisions' / (step + '.' + decision + '.md')

    def events(self, folder):
        return [json.loads(line) for line in (folder / 'runner/events.jsonl').read_text().splitlines()]

    def names(self, folder):
        return [row['event'] for row in self.events(folder)]

    def bytes_of(self, folder):
        return {str(p.relative_to(folder)): p.read_bytes() for p in folder.rglob('*') if p.is_file()}

    def two_branches(self):
        self.write_flow('two-branches', TWO_BRANCHES)
        self.flow('run', 'two-branches')
        folder = self.run_folder('two-branches')
        self.step(folder, 'gate.md', 'One proposed change.\n')
        return folder

    def refuse(self, folder, step='gate'):
        return self.flow('run', '--resume', folder.name, '--no', step, '--words', 'Stop this run.', expected=1)

    def assert_offers_nothing(self, output):
        for text in ('NEXT  ', 'WAITS FOR', 'Then run:'):
            self.assertNotIn(text, output)

    # ------------------------------------------------------------ the files and the words

    def test_both_shipped_workflows_are_valid(self):
        data = json.loads(self.flow('status', '--json'))
        self.assertEqual({row['flow'] for row in data['flows']}, {'operate-amazon', 'produce-ugc-ads'})
        for row in data['flows']:
            self.assertTrue(row['valid'], row['problems'])
        ugc = next(row for row in data['flows'] if row['flow'] == 'produce-ugc-ads')
        self.assertEqual((ugc['steps'], ugc['skills_bound'], ugc['skills_built'], ugc['gates']), (7, 3, 1, ['send']))

    def test_dry_run_names_a_skill_that_is_not_built_and_makes_nothing(self):
        output = self.flow('run', 'produce-ugc-ads', '--input', 'product=watch', '--dry-run')
        self.assertIn('video-assemble (not built)', output)
        self.assertIn('check-required-shots (not built)', output)
        self.assertIn('skill not bound', output)
        self.assertIn('send gate', output)
        self.assertEqual(list((self.home / 'runs').iterdir()), [])

    def test_run_needs_its_required_input(self):
        self.assertIn('missing --input: listing=', self.flow('run', 'operate-amazon', expected=2))
        self.assertEqual(list((self.home / 'runs').iterdir()), [])

    def test_run_makes_the_run_folder_and_names_the_next_step(self):
        folder, output = self.start_amazon()
        self.assertIn('State: running', output)
        self.assertIn('NEXT  audit', output)
        self.assertIn(str(self.portfolio / 'cedar-shop/team/amazon-operator.md'), output)
        self.assertIn(str(folder / 'audit.md'), output)
        frozen = json.loads((folder / 'runner/run.yaml').read_text())
        self.assertEqual(frozen['inputs'], {'listing': 'B0TEST'})
        self.assertEqual(len(frozen['definition_sha256']), 64)
        self.assertNotIn('NEXT  check', output)

    def test_status_reads_and_writes_nothing(self):
        folder, _ = self.start_amazon()
        (folder / 'audit.md').write_text('findings\n')
        before = {p.name: p.read_bytes() for p in folder.iterdir() if p.is_file()}
        overall, steps = self.states(folder)
        self.assertEqual((steps['audit'], steps['check']), ('result-in', 'waiting'))
        self.assertIn('run --resume accepts it', self.flow('status', folder.name))
        self.assertEqual(before, {p.name: p.read_bytes() for p in folder.iterdir() if p.is_file()})

    def test_whole_run_ends_only_after_the_recorded_yes(self):
        folder = self.to_the_gate()
        self.assertFalse((folder / 'runner/end.json').exists())
        output = self.flow('run', '--resume', folder.name, '--yes', 'decide', '--words', 'Yes, change the title.')
        self.assertIn('State: done', output)
        self.assertEqual(json.loads((folder / 'runner/end.json').read_text())['state'], 'done')
        yes = self.record(folder, 'decide', 'yes').read_text()
        self.assertIn('decision: yes', yes)
        self.assertIn('for: ' + hashlib.sha256((folder / 'decide.md').read_bytes()).hexdigest(), yes)
        self.assertIn('words: Yes, change the title.', yes)
        names = [row['event'] for row in self.events(folder)]
        self.assertEqual((names.count('accepted'), names.count('approval'), names[-1]), (3, 1, 'run-done'))

    def test_a_review_without_a_verdict_line_is_not_accepted(self):
        folder, _ = self.start_amazon()
        self.step(folder, 'audit.md', 'findings\n')
        output = self.step(folder, 'check.md', 'looks fine\n')
        self.assertIn('the first line must be: verdict: pass, or verdict: fail', output)
        self.assertNotIn('NEXT  decide', output)

    def test_a_failed_review_starts_a_repair_round_and_two_rounds_is_the_limit(self):
        folder, _ = self.start_amazon()
        for round_number in (1, 2):
            self.step(folder, 'audit.md', 'findings ' + str(round_number) + '\n')
            output = self.step(folder, 'check.md', 'verdict: fail\nnot cleared\n')
            self.assertIn('NEXT  audit', output)
            self.assertIn('try ' + str(round_number + 1), output)
            self.assertTrue((folder / 'runner/attempts' / str(round_number) / 'check.md').is_file())
            self.assertFalse((folder / 'audit.md').exists())
        self.step(folder, 'audit.md', 'findings 3\n')
        output = self.step(folder, 'check.md', 'verdict: fail\nnot cleared\n', expected=1)
        self.assertIn('State: blocked', output)
        self.assertIn('no repair round is left', output)
        self.assertNotIn('NEXT  decide', output)

    def test_a_repair_round_takes_away_every_result_after_the_repeated_steps(self):
        folder, _ = self.start_amazon()
        self.step(folder, 'audit.md', 'findings\n')
        (folder / 'decide.md').write_text('An early ask.\n')
        self.record(folder, 'decide', 'yes').write_text('yes\n')
        self.step(folder, 'check.md', 'verdict: fail\nnot cleared\n')
        self.assertFalse((folder / 'decide.md').exists())
        self.assertFalse(self.record(folder, 'decide', 'yes').exists())
        self.assertTrue((folder / 'runner/attempts/1/decide.md').is_file())
        repeat = next(row for row in self.events(folder) if row['event'] == 'repeat')
        self.assertEqual(repeat['steps'], ['audit', 'check', 'decide'])

    def test_a_plain_code_step_runs_and_a_failed_one_blocks(self):
        (self.home / 'tools/bad.py').write_text('raise SystemExit(3)\n')
        shape = ('version: 1\nflow: {name}\nkind: flow\npurpose: "Check one thing."\nmembers:\n  mercer: {{seat: mercer}}\n'
                 'graph:\n  prepare:\n    run: [python3, tools/{script}]\n    needs: []\n'
                 '  write:\n    member: mercer\n    skill: log\n    needs: [prepare]\n    done_when: {{file: note.md}}\n')
        self.write_flow('good-check', shape.format(name='good-check', script='change.py'), skill=True)
        self.write_flow('bad-check', shape.format(name='bad-check', script='bad.py'), skill=True)
        output = self.flow('run', 'good-check')
        self.assertIn('NEXT  write', output)
        self.assertIn(str(self.home / 'skills/log/SKILL.md'), output)
        self.assertEqual((self.run_folder('good-check') / 'changed').read_text(), 'changed')
        output = self.flow('run', 'bad-check', expected=1)
        self.assertIn('State: blocked', output)
        self.assertIn('exit 3', output)

    def test_reader_nul_argument_refuses_before_any_code(self):
        self.write_flow('bad-command', json.dumps({'version': 1, 'flow': 'bad-command', 'purpose': 'Reject NUL before running code.', 'graph': {'first': {'run': ['python3', 'tools/change.py']}, 'second': {'run': ['python3', 'tools/change.py', '\0']}}}))
        self.flow('run', 'bad-command', '--dry-run', expected=2)
        self.flow('run', 'bad-command', expected=2)
        self.assertEqual(list((self.home / 'runs').iterdir()), [])

    def test_reader_failed_start_and_status_return_failure(self):
        (self.home / 'tools/fail.py').write_text('raise SystemExit(7)\n')
        self.write_flow('fail-now', json.dumps({'version': 1, 'flow': 'fail-now', 'purpose': 'Propagate failure.', 'graph': {'first': {'run': ['python3', 'tools/fail.py']}, 'later': {'run': ['python3', 'tools/change.py'], 'needs': ['first']}}}))
        self.flow('run', 'fail-now', expected=1)
        folder = self.run_folder()
        self.flow('status', folder.name, expected=1)
        self.flow('status', folder.name, '--json', expected=1)
        self.assertFalse((folder / 'changed').exists())

    def test_reader_corrupt_frozen_status_is_failure_without_writes(self):
        folder, _ = self.start_amazon()
        file = folder / 'runner/run.yaml'
        data = json.loads(file.read_text())
        data['inputs']['listing'] = 'changed'
        file.write_text(json.dumps(data))
        before = self.bytes_of(folder)
        self.flow('status', folder.name, expected=1)
        self.flow('status', folder.name, '--json', expected=1)
        self.assertEqual(before, self.bytes_of(folder))

    def test_a_bad_file_is_refused_with_every_problem(self):
        self.write_flow('bad-shape', 'version: 2\nflow: other\nextra: 1\nmembers: {}\ngraph:\n'
                        '  a:\n    member: nobody\n    needs: [b]\n    done_when: {file: ../x}\n'
                        '  b:\n    run: [python3, /bin/sh]\n    needs: [a]\n    member: nobody\n')
        output = self.flow('run', 'bad-shape', expected=2)
        for text in ('unknown key: extra', 'version must be 1', 'flow must equal the file name: bad-shape',
                     'purpose must be one sentence', 'member is not in members: nobody',
                     'done_when needs file', 'needs one of member', 'form a circle'):
            self.assertIn(text, output)
        self.assertEqual(list((self.home / 'runs').iterdir()), [])
        self.assertIn('NOT VALID', self.flow('status', expected=1))

    def test_unknown_names_are_refused(self):
        self.assertIn('no flow named nothing-here', self.flow('run', 'nothing-here', expected=2))
        self.assertIn('a flow name has lowercase letters', self.flow('run', 'Bad_Name', expected=2))
        self.assertIn('no run named', self.flow('status', '2026-01-01-none', expected=2))
        self.assertIn('give a flow name to start', self.flow('run', expected=2))
        self.assertIn('go with --resume', self.flow('run', 'operate-amazon', '--yes', 'decide', expected=2))

    # ------------------------------------------------------------ order: the reader's probes and their kin

    def test_order_a_result_before_its_dependency_does_not_advance_the_run(self):
        # Probe "unmet dependencies": check.md passes, audit.md is not there. decide must not be offered.
        folder, _ = self.start_amazon()
        (folder / 'check.md').write_text('verdict: pass\n')
        output = self.flow('run', '--resume', folder.name)
        self.assertNotIn('NEXT  decide', output)
        self.assertIn('NEXT  audit', output)
        overall, steps = self.states(folder)
        self.assertEqual((steps['audit'], steps['check'], steps['decide']), ('ready', 'early', 'waiting'))
        self.assertNotIn('accepted', [row['event'] for row in self.events(folder)])

    def test_order_an_early_result_stays_out_after_its_dependency_is_done(self):
        folder, _ = self.start_amazon()
        (folder / 'check.md').write_text('verdict: pass\n')
        output = self.step(folder, 'audit.md', 'findings\n')
        self.assertIn('written before the steps it needs were done; write it again', output)
        self.assertIn('NEXT  check', output)
        self.assertNotIn('NEXT  decide', output)
        self.assertEqual([row['step'] for row in self.events(folder) if row['event'] == 'accepted'], ['audit'])
        output = self.step(folder, 'check.md', 'verdict: pass\nread the audit\n')
        self.assertIn('NEXT  decide', output)

    def test_order_status_judges_each_step_after_the_steps_it_needs(self):
        # stand() may not call a step done because its file is there. Every file is here; nothing was accepted.
        folder, _ = self.start_amazon()
        for name, text in (('check.md', 'verdict: pass\n'), ('decide.md', 'ask\n'), ('decide.yes.md', 'yes\n')):
            (folder / name).write_text(text)
        overall, steps = self.states(folder)
        self.assertEqual(overall, 'running')
        self.assertEqual(steps, {'audit': 'ready', 'check': 'early', 'decide': 'early'})

    def test_order_an_accepted_result_that_changes_blocks_the_run(self):
        folder, _ = self.start_amazon()
        self.step(folder, 'audit.md', 'findings\n')
        output = self.step(folder, 'audit.md', 'other findings\n', expected=1)
        self.assertIn('State: blocked', output)
        self.assertIn('the result changed after it was accepted', output)
        self.assertNotIn('NEXT  check', output)

    # ------------------------------------------------------------ gates: the reader's probes and their kin

    def test_gate_free_text_that_says_no_is_not_a_yes(self):
        # Probe "negative approval": a refusal written into decide.yes.md completed the run.
        folder = self.to_the_gate()
        self.record(folder, 'decide', 'yes').write_text('NO. Do not change the listing.')
        output = self.flow('run', '--resume', folder.name)
        self.assertIn('State: waits for avery', output)
        self.assertIn('is not a recorded yes', output)
        self.assertFalse((folder / 'runner/end.json').exists())

    def test_gate_any_text_in_the_yes_file_is_not_a_yes(self):
        folder = self.to_the_gate()
        for text in ('yes', 'approved, go ahead', 'decision: yes\nwords: go\n',
                     'decision: yes\nfor: ' + 'a' * 64 + '\nwords: go\n'):
            self.record(folder, 'decide', 'yes').write_text(text)
            self.assertIn('State: waits for avery', self.flow('run', '--resume', folder.name))
        self.assertFalse((folder / 'runner/end.json').exists())

    def test_gate_a_yes_file_with_words_that_refuse_is_not_a_yes(self):
        folder = self.to_the_gate()
        bound = hashlib.sha256((folder / 'decide.md').read_bytes()).hexdigest()
        self.record(folder, 'decide', 'yes').write_text('decision: yes\nfor: ' + bound + '\nby: mercer\nat: ' + NOW + '\nwords: NO. Do not change the listing.\n')
        output = self.flow('run', '--resume', folder.name)
        self.assertIn('State: waits for avery', output)
        self.assertIn('the words read as a no', output)
        output = self.flow('run', '--resume', folder.name, '--yes', 'decide', '--words', "Don't do it.", expected=2)
        self.assertIn('the words read as a no', output)
        self.assertIn('--words is needed', self.flow('run', '--resume', folder.name, '--yes', 'decide', expected=2))

    def test_gate_a_recorded_no_stops_the_run_for_good(self):
        folder = self.to_the_gate()
        output = self.flow('run', '--resume', folder.name, '--no', 'decide', '--words', 'No. Leave the title.', expected=1)
        self.assertIn('State: refused\n', output)
        self.assertIn('the person said no: No. Leave the title.', output)
        self.assert_offers_nothing(output)
        bound = hashlib.sha256((folder / 'decide.md').read_bytes()).hexdigest()
        self.record(folder, 'decide', 'yes').write_text('decision: yes\nfor: ' + bound + '\nwords: go\n')
        self.assertIn('State: refused\n', self.flow('run', '--resume', folder.name, expected=1))
        self.assertEqual(json.loads((folder / 'runner/end.json').read_text())['state'], 'refused')

    def test_gate_a_yes_is_for_one_exact_result(self):
        folder = self.to_the_gate()
        old = hashlib.sha256(b'One ask: change the price.\n').hexdigest()
        self.record(folder, 'decide', 'yes').write_text('decision: yes\nfor: ' + old + '\nby: mercer\nat: ' + NOW + '\nwords: go\n')
        output = self.flow('run', '--resume', folder.name)
        self.assertIn('the yes is for another version', output)
        self.assertIn('State: waits for avery', output)
        self.record(folder, 'decide', 'yes').unlink()
        self.flow('run', '--resume', folder.name, '--yes', 'decide', '--words', 'Go.')
        self.assertEqual(self.states(folder)[0], 'done')

    def test_gate_a_code_step_does_not_run_before_its_yes(self):
        # Probe "gate on code": the gated command ran and the run ended done with no yes.
        self.write_flow('code-gate', CODE_GATE)
        output = self.flow('run', 'code-gate')
        folder = self.run_folder('code-gate')
        self.assertIn('State: waits for avery', output)
        self.assertIn('to run  python3 tools/change.py', output)
        self.assertFalse((folder / 'changed').exists())
        self.record(folder, 'publish', 'yes').write_text('yes do it')
        self.assertIn('State: waits for avery', self.flow('run', '--resume', folder.name))
        self.assertFalse((folder / 'changed').exists())
        self.assertNotIn('code-step', [row['event'] for row in self.events(folder)])
        self.record(folder, 'publish', 'yes').unlink()
        output = self.flow('run', '--resume', folder.name, '--yes', 'publish', '--words', 'Yes. Publish it.')
        self.assertIn('State: done', output)
        self.assertEqual((folder / 'changed').read_text(), 'changed')

    def test_gate_a_refused_code_step_never_runs(self):
        self.write_flow('code-gate', CODE_GATE)
        self.flow('run', 'code-gate')
        folder = self.run_folder('code-gate')
        output = self.flow('run', '--resume', folder.name, '--no', 'publish', '--words', 'No.', expected=1)
        self.assertIn('State: refused\n', output)
        self.flow('run', '--resume', folder.name, expected=1)
        self.assertFalse((folder / 'changed').exists())

    def test_gate_a_yes_for_a_code_step_does_not_carry_to_another_run(self):
        self.write_flow('code-gate', CODE_GATE)
        self.flow('run', 'code-gate')
        first = self.run_folder('code-gate')
        self.flow('run', '--resume', first.name, '--yes', 'publish', '--words', 'Yes.')
        self.flow('run', 'code-gate')
        second = self.run_folder('code-gate-2')
        shutil.copyfile(self.record(first, 'publish', 'yes'), self.record(second, 'publish', 'yes'))
        output = self.flow('run', '--resume', second.name)
        self.assertIn('the yes is for another version', output)
        self.assertFalse((second / 'changed').exists())

    def test_gate_only_a_step_that_waits_can_get_a_yes(self):
        folder, _ = self.start_amazon()
        output = self.flow('run', '--resume', folder.name, '--yes', 'decide', '--words', 'Yes.', expected=2)
        self.assertIn('does not wait for a yes now', output)
        output = self.flow('run', '--resume', folder.name, '--yes', 'audit', '--words', 'Yes.', expected=2)
        self.assertIn('has no gate', output)
        self.assertFalse(self.record(folder, 'decide', 'yes').exists())


    def test_gate_a_yes_file_the_runner_did_not_record_is_not_a_yes(self):
        # A hand can write the right form with the right hash. Only a yes recorded with --yes counts.
        folder = self.to_the_gate()
        bound = hashlib.sha256((folder / 'decide.md').read_bytes()).hexdigest()
        self.record(folder, 'decide', 'yes').write_text('decision: yes\nfor: ' + bound + '\nby: mercer\nat: ' + NOW + '\nwords: Go ahead.\n')
        output = self.flow('run', '--resume', folder.name)
        self.assertIn('State: waits for avery', output)
        self.assertIn('this yes was not recorded by the runner', output)
        self.assertFalse((folder / 'runner/end.json').exists())

    def test_gate_a_yes_file_written_with_the_result_does_not_pass_on_acceptance(self):
        # The member writes the result and its own yes in one go, before code accepts the result.
        folder, _ = self.start_amazon()
        self.step(folder, 'audit.md', 'findings\n')
        self.step(folder, 'check.md', 'verdict: pass\n')
        (folder / 'decide.md').write_text('One ask.\n')
        bound = hashlib.sha256(b'One ask.\n').hexdigest()
        self.record(folder, 'decide', 'yes').write_text('decision: yes\nfor: ' + bound + '\nwords: Go ahead.\n')
        self.assertIn('State: waits for avery', self.flow('run', '--resume', folder.name))

    def test_gate_a_yes_file_with_a_key_twice_is_not_a_yes(self):
        folder = self.to_the_gate()
        self.flow('run', '--resume', folder.name, '--yes', 'decide', '--words', 'Go.')
        self.assertEqual(self.states(folder)[0], 'done')
        folder2 = None
        self.flow('run', 'operate-amazon', '--workspace', 'cedar-shop', '--input', 'listing=B0TWO')
        folder2 = self.run_folder('operate-amazon-2')
        self.step(folder2, 'audit.md', 'findings\n')
        self.step(folder2, 'check.md', 'verdict: pass\n')
        self.step(folder2, 'decide.md', 'One ask.\n')
        bound = hashlib.sha256(b'One ask.\n').hexdigest()
        self.record(folder2, 'decide', 'yes').write_text('decision: no\ndecision: yes\nfor: ' + bound + '\nwords: Go.\n')
        output = self.flow('run', '--resume', folder2.name)
        self.assertIn('State: waits for avery', output)
        self.assertIn('is not a recorded yes', output)

    def test_gate_a_yes_recorded_twice_is_refused_the_second_time(self):
        folder = self.to_the_gate()
        self.flow('run', '--resume', folder.name, '--yes', 'decide', '--words', 'Go.')
        before = self.bytes_of(folder)
        output = self.flow('run', '--resume', folder.name, '--yes', 'decide', '--words', 'Go again.', expected=2)
        self.assertIn('this run is done. No decision is recorded', output)
        self.assertEqual(before, self.bytes_of(folder))
        self.assertEqual(self.names(folder).count('approval'), 1)

    def test_gate_a_changed_result_after_its_yes_blocks_a_run_that_is_not_done(self):
        self.write_flow('gate-then-more', 'version: 1\nflow: gate-then-more\npurpose: "A gate, then one more step."\n'
                        'members:\n  worker: {seat: mercer}\ngraph:\n'
                        '  ask:\n    member: worker\n    gate: send\n    done_when: {file: ask.md}\n'
                        '  send:\n    member: worker\n    needs: [ask]\n    done_when: {file: send.md}\n')
        self.flow('run', 'gate-then-more')
        folder = self.run_folder('gate-then-more')
        self.step(folder, 'ask.md', 'Send this text.\n')
        self.flow('run', '--resume', folder.name, '--yes', 'ask', '--words', 'Yes, send it.')
        (folder / 'ask.md').write_text('Send another text.\n')
        output = self.step(folder, 'send.md', 'sent\n', expected=1)
        self.assertIn('State: blocked', output)
        self.assertIn('the result changed after it was accepted', output)
        self.assert_offers_nothing(output)
        self.assertEqual(self.names(folder).count('accepted'), 1)

    # ------------------------------------------------------------ a no is final: the second reader's probe and its kin

    def test_refusal_another_branch_does_not_go_on(self):
        # Probe: a no on gate, then prepare.md arrives. It was accepted and the code step change ran.
        folder = self.two_branches()
        self.refuse(folder)
        before = self.bytes_of(folder)
        output = self.step(folder, 'prepare.md', 'Independent preparation complete.\n', expected=1)
        self.assertFalse((folder / 'changed').exists())
        self.assertNotIn('code-step', self.names(folder))
        self.assertEqual([row['step'] for row in self.events(folder) if row['event'] == 'accepted'], ['gate'])
        before['prepare.md'] = b'Independent preparation complete.\n'
        self.assertEqual(before, self.bytes_of(folder))
        self.assertIn('State: refused\n', output)
        self.assertIn('Nothing was changed: this run is refused.', output)

    def test_refusal_a_result_that_is_already_there_is_not_accepted_by_the_no(self):
        # The need of the code step is in the other branch, and its result is on disk when the no comes.
        folder = self.two_branches()
        (folder / 'prepare.md').write_text('Ready before the no.\n')
        output = self.refuse(folder)
        self.assertIn('State: refused\n', output)
        self.assertFalse((folder / 'changed').exists())
        self.assertEqual([row['step'] for row in self.events(folder) if row['event'] == 'accepted'], ['gate'])
        self.assertNotIn('code-step', self.names(folder))

    def test_refusal_a_resume_changes_nothing_and_says_so(self):
        folder = self.two_branches()
        self.refuse(folder)
        before = self.bytes_of(folder)
        for _ in range(2):
            output = self.flow('run', '--resume', folder.name, expected=1)
            self.assertIn('Nothing was changed: this run is refused.', output)
            self.assert_offers_nothing(output)
        self.assertEqual(before, self.bytes_of(folder))
        self.assertEqual(self.names(folder)[-1], 'run-refused')

    def test_refusal_the_status_readout_offers_nothing(self):
        folder = self.two_branches()
        self.refuse(folder)
        output = self.flow('status', folder.name, expected=1)
        self.assertIn('State: refused\n', output)
        self.assertIn('This run is over: avery said no.', output)
        self.assertIn('Only a new run starts work again', output)
        self.assert_offers_nothing(output)
        overall, steps = self.states(folder)
        self.assertEqual((overall, steps), ('refused', {'gate': 'refused', 'prepare': 'stopped', 'change': 'stopped'}))
        self.assertIn(folder.name + ': refused', self.flow('status'))
        self.assertEqual(json.loads((folder / 'runner/end.json').read_text())['state'], 'refused')

    def test_refusal_takes_no_yes_and_no_other_decision_after_it(self):
        folder = self.two_branches()
        self.refuse(folder)
        before = self.bytes_of(folder)
        for flag in ('--yes', '--no'):
            output = self.flow('run', '--resume', folder.name, flag, 'gate', '--words', 'Yes after all.', expected=2)
            self.assertIn('this run is refused. No decision is recorded', output)
        self.assertEqual(before, self.bytes_of(folder))

    def test_refusal_a_no_file_written_by_hand_ends_the_run_too(self):
        folder = self.two_branches()
        self.record(folder, 'gate', 'no').write_text('He said no on the phone.\n')
        (folder / 'prepare.md').write_text('ready\n')
        output = self.flow('run', '--resume', folder.name, expected=1)
        self.assertIn('State: refused\n', output)
        self.assertFalse((folder / 'changed').exists())
        self.assertEqual(self.names(folder)[-1], 'run-refused')
        self.assertIn('this run is refused', self.flow('run', '--resume', folder.name, '--yes', 'gate', '--words', 'Yes.', expected=2))

    def test_refusal_can_come_before_the_step_is_offered(self):
        folder, _ = self.start_amazon()
        output = self.flow('run', '--resume', folder.name, '--no', 'decide', '--words', 'Do not touch this listing.', expected=1)
        self.assertIn('State: refused\n', output)
        self.assert_offers_nothing(output)
        self.step(folder, 'audit.md', 'findings\n', expected=1)
        self.assertNotIn('accepted', self.names(folder))

    def test_a_new_run_starts_work_again_after_a_refusal(self):
        folder = self.two_branches()
        self.refuse(folder)
        output = self.flow('run', 'two-branches')
        self.assertIn('State: running', output)
        self.assertIn('NEXT  gate', output)
        self.assertEqual(self.states(self.run_folder('two-branches-2'))[0], 'running')

    # ------------------------------------------------------------ the end of a run, and a blocked run

    def test_done_is_final_a_resume_changes_nothing(self):
        folder = self.to_the_gate()
        self.flow('run', '--resume', folder.name, '--yes', 'decide', '--words', 'Go.')
        before = self.bytes_of(folder)
        (folder / 'audit.md').write_text('late edit\n')
        output = self.flow('run', '--resume', folder.name)
        self.assertIn('Nothing was changed: this run is done.', output)
        before['audit.md'] = b'late edit\n'
        self.assertEqual(before, self.bytes_of(folder))

    def test_blocked_a_failed_code_step_stops_the_other_branch_and_is_not_run_again(self):
        (self.home / 'tools/bad.py').write_text('raise SystemExit(3)\n')
        self.write_flow('half-broken', 'version: 1\nflow: half-broken\npurpose: "One branch fails."\n'
                        'members:\n  worker: {seat: mercer}\ngraph:\n'
                        '  check:\n    run: [python3, tools/bad.py]\n'
                        '  prepare:\n    member: worker\n    done_when: {file: prepare.md}\n'
                        '  change:\n    run: [python3, tools/change.py]\n    needs: [prepare]\n')
        output = self.flow('run', 'half-broken', expected=1)
        folder = self.run_folder('half-broken')
        self.assertIn('State: blocked', output)
        self.assert_offers_nothing(output)
        output = self.step(folder, 'prepare.md', 'ready\n', expected=1)
        self.assertIn('This run is blocked.', output)
        self.assertFalse((folder / 'changed').exists())
        self.assertNotIn('accepted', self.names(folder))
        self.assertEqual(self.names(folder).count('code-step'), 1)

    # ------------------------------------------------------------ files that must not count

    def test_file_an_empty_result_a_link_and_a_name_not_in_the_graph_do_not_count(self):
        folder, _ = self.start_amazon()
        (folder / 'audit.md').write_text('  \n\n')
        self.assertEqual(self.states(folder)[1]['audit'], 'ready')
        (folder / 'audit.md').unlink()
        outside = Path(self.temp.name) / 'outside.md'
        outside.write_text('findings from somewhere else\n')
        (folder / 'audit.md').symlink_to(outside)
        (folder / 'extra.md').write_text('a file no step names\n')
        (folder / 'audit.yes.md').write_text('decision: yes\n')
        output = self.flow('run', '--resume', folder.name)
        self.assertIn('NEXT  audit', output)
        self.assertNotIn('accepted', self.names(folder))

    def test_file_run_yaml_changed_after_the_start_blocks_the_run(self):
        # Take the gate out of the frozen definition. The run must not go on with the changed file.
        folder = self.to_the_gate()
        info = json.loads((folder / 'runner/run.yaml').read_text())
        del info['definition']['graph']['decide']['gate']
        (folder / 'runner/run.yaml').write_text(json.dumps(info))
        output = self.flow('run', '--resume', folder.name, expected=1)
        self.assertIn('State: blocked', output)
        self.assertIn('run.yaml is not the file this run started with', output)
        self.assertFalse((folder / 'runner/end.json').exists())

    def test_file_a_script_that_is_a_link_out_of_the_home_does_not_run(self):
        outside = Path(self.temp.name) / 'outside.py'
        outside.write_text("import os, pathlib\npathlib.Path(os.environ['FOXRUN_RUN_DIR'], 'changed').write_text('x')\n")
        (self.home / 'tools/linked.py').symlink_to(outside)
        self.write_flow('linked', 'version: 1\nflow: linked\npurpose: "Run a linked script."\ngraph:\n  go:\n    run: [python3, tools/linked.py]\n')
        # Round 8: the script is checked before the run starts. No run is made, and nothing runs.
        output = self.flow('run', 'linked', expected=2)
        self.assertIn('the script is not a file inside the system home: tools/linked.py', output)
        self.assertEqual(list((self.home / 'runs').iterdir()), [])
        self.assertIn('NOT VALID', self.flow('status', expected=1))

    def test_file_a_script_that_becomes_a_link_out_of_the_home_after_the_start_does_not_run(self):
        # The rule of the test above, for a run that is already there: the script is checked again when the run is read.
        outside = Path(self.temp.name) / 'outside.py'
        outside.write_text("import os, pathlib\npathlib.Path(os.environ['FOXRUN_RUN_DIR'], 'changed').write_text('x')\n")
        (self.home / 'tools/later.py').write_text('raise SystemExit(0)\n')
        self.write_flow('later', 'version: 1\nflow: later\npurpose: "Run a script after a step."\nmembers:\n  worker: {seat: mercer}\ngraph:\n'
                        '  prepare:\n    member: worker\n    done_when: {file: prepare.md}\n'
                        '  go:\n    run: [python3, tools/later.py]\n    needs: [prepare]\n')
        self.flow('run', 'later')
        folder = self.run_folder('later')
        (self.home / 'tools/later.py').unlink()
        (self.home / 'tools/later.py').symlink_to(outside)
        output = self.step(folder, 'prepare.md', 'ready\n', expected=1)
        self.assertIn('State: blocked', output)
        self.assertIn('the script is not a file inside the system home: tools/later.py', output)
        self.assertFalse((folder / 'changed').exists())
        self.assertNotIn('accepted', self.names(folder))

    def test_definition_a_step_named_twice_and_a_step_that_needs_itself_are_refused(self):
        self.write_flow('twice', 'version: 1\nflow: twice\npurpose: "One name, two steps."\nmembers:\n  worker: {seat: mercer}\ngraph:\n'
                        '  ask:\n    member: worker\n    gate: send\n    done_when: {file: ask.md}\n'
                        '  ask:\n    member: worker\n    done_when: {file: ask2.md}\n')
        self.assertIn('FAIL flow run', self.flow('run', 'twice', expected=2))
        self.write_flow('selfish', 'version: 1\nflow: selfish\npurpose: "A step needs itself."\nmembers:\n  worker: {seat: mercer}\ngraph:\n'
                        '  ask:\n    member: worker\n    needs: [ask]\n    done_when: {file: ask.md}\n')
        self.assertIn('needs itself', self.flow('run', 'selfish', expected=2))
        self.assertEqual(list((self.home / 'runs').iterdir()), [])


    # ------------------------------------------------------------ a dry run changes nothing: the third reader's probe 1 and its kin

    def test_dry_run_with_resume_accepts_nothing_and_runs_no_code(self):
        # Probe 1: run --resume <run> --dry-run accepted prepare.md and ran the code step.
        folder = self.prepare_change()
        before = self.bytes_of(folder)
        output = self.flow('run', '--resume', folder.name, '--dry-run')
        self.assertEqual(before, self.bytes_of(folder))
        self.assertFalse((folder / 'changed').exists())
        self.assertIn('Dry run: nothing was changed. A real call would first:', output)
        self.assertIn('accept the result of prepare', output)
        self.flow('run', '--resume', folder.name)
        self.assertEqual((folder / 'changed').read_text(), 'changed')

    def test_dry_run_with_yes_and_with_no_records_no_decision(self):
        folder = self.to_the_gate()
        before = self.bytes_of(folder)
        output = self.flow('run', '--resume', folder.name, '--dry-run', '--yes', 'decide', '--words', 'Go.')
        self.assertIn('record the yes for decide', output)
        output = self.flow('run', '--resume', folder.name, '--dry-run', '--no', 'decide', '--words', 'Stop.')
        self.assertIn('record the no for decide: the run ends as refused', output)
        output = self.flow('run', '--resume', folder.name, '--dry-run', '--yes', 'audit', '--words', 'Go.')
        self.assertIn('refuse the yes: step audit has no gate', output)
        output = self.flow('run', '--resume', folder.name, '--dry-run', '--yes', 'decide', '--words', 'No, stop.')
        self.assertIn('refuse the yes: the words read as a no', output)
        self.assertEqual(before, self.bytes_of(folder))
        self.assertEqual(self.states(folder)[0], 'waits for avery')

    def test_dry_run_with_yes_runs_no_gated_code_step(self):
        self.write_flow('code-gate', CODE_GATE)
        self.flow('run', 'code-gate')
        folder = self.run_folder('code-gate')
        before = self.bytes_of(folder)
        output = self.flow('run', '--resume', folder.name, '--dry-run', '--yes', 'publish', '--words', 'Yes. Publish it.')
        self.assertIn('record the yes for publish', output)
        self.assertEqual(before, self.bytes_of(folder))
        self.assertFalse((folder / 'changed').exists())

    def test_dry_run_on_a_run_that_is_over_or_blocked_changes_nothing(self):
        folder = self.two_branches()
        self.refuse(folder)
        (self.home / 'tools/bad.py').write_text('raise SystemExit(3)\n')     # the script is on disk before the run starts
        blocked = self.prepare_change(script='bad.py')
        self.flow('run', '--resume', blocked.name, expected=1)
        for run, word in ((folder, 'refused'), (blocked, 'blocked')):
            before = self.bytes_of(run)
            output = self.flow('run', '--resume', run.name, '--dry-run')
            self.assertIn('change nothing more: this run is ' + word, output)
            output = self.flow('run', '--resume', run.name, '--dry-run', '--no', 'gate', '--words', 'Stop.')
            self.assertEqual(before, self.bytes_of(run))

    def test_dry_run_of_a_new_run_makes_nothing_with_any_other_flag(self):
        self.write_flow('code-first', 'version: 1\nflow: code-first\npurpose: "Code first."\ngraph:\n  go:\n    run: [python3, tools/change.py]\n')
        runs = self.home / 'runs'
        self.flow('run', 'code-first', '--dry-run')
        self.flow('run', 'operate-amazon', '--dry-run', '--workspace', 'cedar-shop', '--input', 'listing=B0TEST')
        self.assertIn('go with --resume', self.flow('run', 'code-first', '--dry-run', '--yes', 'go', '--words', 'Go.', expected=2))
        self.assertIn('go with a new run', self.flow('run', '--resume', 'x', '--dry-run', '--input', 'a=b', expected=2))
        self.assertEqual(list(runs.iterdir()), [])

    def test_dry_run_needs_no_lock_and_leaves_a_lock_alone(self):
        folder = self.prepare_change()
        (folder / 'runner/lock').write_text(json.dumps({'pid': os.getpid(), 'at': 'now', 'word': 'test'}) + '\n')
        before = self.bytes_of(folder)
        self.flow('run', '--resume', folder.name, '--dry-run')
        self.flow('status', folder.name)
        self.assertEqual(before, self.bytes_of(folder))

    # ------------------------------------------------------------ one program at a time: the third reader's probe 2 and its kin

    def test_lock_two_resumes_at_once_run_the_code_step_once(self):
        # Probe 2: the second resume started while the code step of the first one ran. Both ran it.
        folder = self.prepare_change(script='slow.py')
        first = self.popen('run', '--resume', folder.name)
        self.wait_for(folder / 'executions.txt')
        second = self.popen('run', '--resume', folder.name)
        output_second = second.communicate(timeout=20)[0]
        first.communicate(timeout=20)
        self.assertEqual((first.returncode, second.returncode), (0, 3))
        self.assertIn('another flow.py works on this run now', output_second)
        self.assertIn('Nothing was changed', output_second)
        self.assertEqual((folder / 'executions.txt').read_text(), 'executed\n')
        names = self.names(folder)
        self.assertEqual((names.count('code-start'), names.count('code-step')), (1, 1))
        self.assertFalse((folder / 'runner/lock').exists())

    def test_lock_a_decision_from_a_second_caller_is_not_recorded(self):
        self.write_flow('slow-then-gate', 'version: 1\nflow: slow-then-gate\npurpose: "Slow code, and a gate."\n'
                        'members:\n  worker: {seat: mercer}\ngraph:\n'
                        '  slow:\n    run: [python3, tools/slow.py]\n'
                        '  ask:\n    member: worker\n    gate: send\n    done_when: {file: ask.md}\n')
        (self.home / 'tools/slow.py').write_text(SLOW)
        first = self.popen('run', 'slow-then-gate')
        self.wait_for(self.home / 'runs')
        until = time.monotonic() + 8
        while not list((self.home / 'runs').glob('*/executions.txt')) and time.monotonic() < until:
            time.sleep(0.01)
        folder = next(p for p in (self.home / 'runs').iterdir())
        for flag in ('--yes', '--no'):
            output = self.flow('run', '--resume', folder.name, flag, 'ask', '--words', 'A word.', expected=3)
            self.assertIn('another flow.py works on this run now', output)
        first.communicate(timeout=20)
        self.assertNotIn('approval', self.names(folder))
        self.assertFalse(self.record(folder, 'ask', 'no').exists())
        self.assertEqual(self.states(folder)[0], 'running')

    def test_lock_a_stale_lock_is_reported_and_not_removed(self):
        folder = self.prepare_change()
        gone = subprocess.Popen([PYTHON, '-c', 'pass'])
        gone.wait()
        (folder / 'runner/lock').write_text(json.dumps({'pid': gone.pid, 'at': '2026-10-13T10:00:00-04:00', 'word': 'run --resume'}) + '\n')
        before = self.bytes_of(folder)
        output = self.flow('run', '--resume', folder.name, expected=3)
        self.assertIn('this run has a stale lock: process ' + str(gone.pid), output)
        self.assertIn('the lock was not removed', output)
        self.assertEqual(before, self.bytes_of(folder))
        (folder / 'runner/lock').write_text('not json')
        self.assertIn('the lock file can not be read', self.flow('run', '--resume', folder.name, expected=3))
        (folder / 'runner/lock').unlink()
        self.flow('run', '--resume', folder.name)
        self.assertEqual((folder / 'changed').read_text(), 'changed')

    def test_lock_a_killed_runner_leaves_a_start_with_no_end_and_the_step_is_not_run_again(self):
        # The runner dies between "the attempt started" and its result.
        folder = self.prepare_change(script='kill.py')
        died = self.popen('run', '--resume', folder.name)
        died.communicate(timeout=20)
        self.assertEqual(died.returncode, -signal.SIGKILL)
        names = self.names(folder)
        self.assertEqual((names.count('code-start'), names.count('code-step')), (1, 0))
        output = self.flow('run', '--resume', folder.name, expected=3)
        self.assertIn('this run has a stale lock', output)
        self.assertEqual((folder / 'executions.txt').read_text(), 'executed\n')
        (folder / 'runner/lock').unlink()
        output = self.flow('run', '--resume', folder.name, expected=1)
        self.assertIn('State: blocked', output)
        self.assertIn('the code step started and no end was recorded; it may have run; it is not run again', output)
        self.assert_offers_nothing(output)
        self.assertEqual((folder / 'executions.txt').read_text(), 'executed\n')
        self.assertEqual(self.names(folder).count('code-start'), 1)

    def test_lock_a_run_folder_that_can_not_be_written_fails_at_once(self):
        folder = self.prepare_change()
        before = self.bytes_of(folder)
        os.chmod(str(folder), stat.S_IRUSR | stat.S_IXUSR)
        self.addCleanup(os.chmod, str(folder), 0o755)
        output = self.flow('run', '--resume', folder.name, expected=3)
        self.assertIn('the run folder can not be written', output)
        self.assertIn('Nothing was changed', output)
        self.flow('status', folder.name)
        self.flow('run', '--resume', folder.name, '--dry-run')
        os.chmod(str(folder), 0o755)
        self.assertEqual(before, self.bytes_of(folder))
        self.assertFalse((folder / 'changed').exists())

    def test_lock_a_runs_folder_that_can_not_be_written_starts_no_run(self):
        runs = self.home / 'runs'
        os.chmod(str(runs), stat.S_IRUSR | stat.S_IXUSR)
        self.addCleanup(os.chmod, str(runs), 0o755)
        output = self.flow('run', 'operate-amazon', '--workspace', 'cedar-shop', '--input', 'listing=B0TEST', expected=3)
        self.assertIn('the runs folder can not be written', output)
        os.chmod(str(runs), 0o755)
        self.assertEqual(list(runs.iterdir()), [])

    def test_lock_two_new_runs_at_once_get_two_folders(self):
        self.prepare_change()
        both = [self.popen('run', 'prepare-change') for _ in range(2)]
        for process in both:
            process.communicate(timeout=20)
        self.assertEqual([process.returncode for process in both], [0, 0])
        names = sorted(p.name for p in (self.home / 'runs').iterdir())
        self.assertEqual(len(names), 3)
        self.assertEqual(len(set(names)), 3)
        for name in names:
            self.assertEqual(self.names(self.home / 'runs' / name)[0], 'run-start')

    def test_lock_a_repair_round_that_was_cut_off_is_finished_by_the_next_resume(self):
        folder, _ = self.start_amazon()
        self.step(folder, 'audit.md', 'findings\n')
        (folder / 'check.md').write_text('verdict: fail\n')
        self.flow('run', '--resume', folder.name, '--dry-run')
        # The state a kill leaves between the plan of the round and the move of its files.
        accepted = {'at': NOW, 'ts': time.time(), 'event': 'accepted', 'step': 'check', 'attempt': 1,
                    'sha256': hashlib.sha256(b'verdict: fail\n').hexdigest(), 'verdict': 'fail'}
        begun = {'at': NOW, 'ts': time.time(), 'event': 'repeat-start', 'step': 'check', 'round': 1, 'steps': ['audit', 'check', 'decide']}
        with (folder / 'runner/events.jsonl').open('a') as stream:
            stream.write(json.dumps(accepted) + '\n' + json.dumps(begun) + '\n')
        self.assertEqual(self.states(folder)[0], 'repair')
        output = self.flow('run', '--resume', folder.name)
        self.assertIn('NEXT  audit', output)
        self.assertIn('try 2', output)
        self.assertTrue((folder / 'runner/attempts/1/audit.md').is_file())
        self.assertTrue((folder / 'runner/attempts/1/check.md').is_file())
        self.assertFalse((folder / 'audit.md').exists())
        self.assertEqual(self.names(folder)[-2:], ['repeat-start', 'repeat'])


    # ------------------------------------------------------------ the files of the runner and the files of the steps never mix

    ONE_STEP = ('version: 1\nflow: {name}\npurpose: "One step."\nmembers:\n  worker: {{seat: mercer}}\ngraph:\n'
                '  prepare:\n    member: worker\n    done_when: {{file: "{file}"}}\n')
    GATE_THEN_STEP = ('version: 1\nflow: {name}\npurpose: "A gate, then a step."\nmembers:\n  worker: {{seat: mercer}}\ngraph:\n'
                      '  approve:\n    member: worker\n    gate: production\n    done_when: {{file: approve.md}}\n'
                      '  execute:\n    member: worker\n    needs: [approve]\n    done_when: {{file: "{file}"}}\n')

    def refused_name(self, file, shape=None, words='is a name of the runner'):
        self.write_flow('names', (shape or self.ONE_STEP).format(name='names', file=file))
        output = self.flow('run', 'names', expected=2)
        self.assertIn(words, output, file)
        self.assertEqual(list((self.home / 'runs').iterdir()), [], file)

    def test_names_a_step_may_not_use_a_file_name_of_the_runner(self):
        # The fourth reader's probes: run.yaml as a result was done at once; result.json was overwritten at the end;
        # events.jsonl was accepted and then changed by the acceptance itself.
        for file in ('run.yaml', 'events.jsonl', 'result.json', 'end.json', 'lock', 'attempts', 'decisions', 'runner', 'start-page.md'):
            self.refused_name(file)

    def test_names_a_step_may_not_use_the_name_of_a_yes_or_a_no(self):
        # The fourth reader's probe: execute had the result file approve.yes.md, and the yes for approve finished it.
        for file in ('approve.yes.md', 'approve.no.md', 'anything.yes.md'):
            self.refused_name(file, shape=self.GATE_THEN_STEP)

    def test_names_capital_and_small_letters_are_one_name(self):
        for file in ('RUN.YAML', 'Run.Yaml', 'Events.JSONL', 'Runner', 'END.json', 'Approve.YES.md', 'LOCK'):
            self.refused_name(file)
        self.refused_name('Approve.MD', shape=self.GATE_THEN_STEP, words='writes the same file as step approve')

    def test_names_two_steps_may_not_have_one_result_file(self):
        self.refused_name('approve.md', shape=self.GATE_THEN_STEP, words='writes the same file as step approve')

    def test_names_a_result_path_may_not_leave_the_top_of_the_run_folder(self):
        for file in ('../outside.md', 'a/../b.md', 'runner/audit.md', 'sub/audit.md', '/tmp/audit.md', '..', '.hidden.md'):
            self.refused_name(file, words='done_when needs file: one file name in the run folder')

    def test_names_a_result_inside_the_reserved_folder_is_never_read(self):
        folder, _ = self.start_amazon()
        (folder / 'runner/audit.md').write_text('findings, put in the wrong place\n')
        (folder / 'runner/decisions').mkdir()
        (folder / 'runner/decisions/audit.md').write_text('findings\n')
        output = self.flow('run', '--resume', folder.name)
        self.assertIn('NEXT  audit', output)
        self.assertNotIn('accepted', self.names(folder))

    def test_names_a_result_that_is_a_link_into_the_reserved_folder_is_not_accepted(self):
        folder, _ = self.start_amazon()
        (folder / 'audit.md').symlink_to(folder / 'runner/run.yaml')
        output = self.flow('run', '--resume', folder.name)
        self.assertIn('NEXT  audit', output)
        self.assertNotIn('accepted', self.names(folder))

    def test_names_a_yes_for_one_gate_finishes_no_other_step(self):
        self.write_flow('gate-then-step', self.GATE_THEN_STEP.format(name='gate-then-step', file='execute.md'))
        self.flow('run', 'gate-then-step')
        folder = self.run_folder('gate-then-step')
        self.step(folder, 'approve.md', 'Do the change.\n')
        output = self.flow('run', '--resume', folder.name, '--yes', 'approve', '--words', 'Yes, do it.')
        self.assertIn('State: running', output)
        self.assertIn('NEXT  execute', output)
        overall, steps = self.states(folder)
        self.assertEqual(steps, {'approve': 'done', 'execute': 'ready'})
        # the record of the yes, copied to every place a hand might try, is not the result of execute
        record = self.record(folder, 'approve', 'yes').read_text()
        self.record(folder, 'execute', 'yes').write_text(record)
        (folder / 'runner/execute.md').write_text(record)
        self.assertEqual(self.states(folder)[1]['execute'], 'ready')
        self.assertFalse((folder / 'runner/end.json').exists())
        self.assertEqual([row['step'] for row in self.events(folder) if row['event'] == 'accepted'], ['approve'])

    def test_names_the_runner_never_writes_or_changes_a_file_of_a_worker(self):
        # A worker leaves files with the names of the end summary of this runner and of the one before.
        folder, _ = self.start_amazon()
        strays = {'end.json': b'{"mine": true}\n', 'result.json': b'{"mine": true}\n', 'notes.md': b'my notes\n'}
        for name, body in strays.items():
            (folder / name).write_bytes(body)
        results = {'audit.md': b'findings\n', 'check.md': b'verdict: pass\n', 'decide.md': b'One ask.\n'}
        for name, body in results.items():
            self.step(folder, name, body.decode())
        self.flow('run', '--resume', folder.name, '--yes', 'decide', '--words', 'Go.')
        self.assertEqual(self.states(folder)[0], 'done')
        top = {p.name: p.read_bytes() for p in folder.iterdir() if p.is_file()}
        self.assertEqual(top, dict(strays, **results))
        self.assertEqual(sorted(p.name for p in folder.iterdir() if p.is_dir()), ['runner'])
        self.assertEqual(json.loads((folder / 'runner/end.json').read_text())['state'], 'done')
        self.assertEqual(sorted(p.name for p in (folder / 'runner').iterdir()), ['decisions', 'end.json', 'events.jsonl', 'run.yaml'])

    def test_names_a_run_folder_of_the_older_shape_is_not_read(self):
        old = self.home / 'runs/2026-10-13-old-shape'
        old.mkdir()
        (old / 'run.yaml').write_text(json.dumps({'run': old.name, 'flow': 'operate-amazon', 'definition': {'graph': {}}}))
        (old / 'events.jsonl').write_text('')
        before = self.bytes_of(old)
        for words in (('run', '--resume', old.name), ('status', old.name), ('run', '--resume', old.name, '--dry-run')):
            self.assertIn('has the shape of an older flow.py', self.flow(*words, expected=2))
        self.assertNotIn(old.name, self.flow('status'))
        self.assertEqual(before, self.bytes_of(old))

    def test_names_a_reserved_folder_that_is_a_link_is_not_read(self):
        folder, _ = self.start_amazon()
        elsewhere = Path(self.temp.name) / 'elsewhere'
        (folder / 'runner').rename(elsewhere)
        (folder / 'runner').symlink_to(elsewhere, target_is_directory=True)
        self.assertIn('is a link. It is not read', self.flow('run', '--resume', folder.name, expected=2))
        # Round 8: status does not pass over it. It lists the run as not readable and ends with 1.
        listing = self.flow('status', expected=1)
        self.assertIn(folder.name + ': NOT READABLE: the run folder, or its folder runner, is a link. It is not read', listing)
        self.assertNotIn(folder.name + ': running', listing)


    # ------------------------------------------------------------ which definition a name means: one resolver for run and status

    def spec(self, name, step, gate=False, kind='flow'):
        return ('version: 1\nflow: ' + name + '\nkind: ' + kind + '\npurpose: "Check which definition is taken."\nmembers:\n  worker: {seat: mercer}\n'
                'graph:\n  ' + step + ':\n    member: worker\n' + ('    gate: catalog\n' if gate else '') + '    done_when: {file: ' + step + '.md}\n')

    def define(self, place, name, text):
        """Write one definition. place: workflows, source, shelf, small-talk, or the name of a workspace."""
        folders = {'workflows': self.home / 'skillwright/workflows', 'source': self.home / 'skillwright/skills',
                   'shelf': self.home / 'skills', 'small-talk': self.home / 'small-talk/skills'}
        file = (folders[place] / (name + '.yaml') if place == 'workflows' else folders[place] / name / 'flow.yaml') \
            if place in folders else self.portfolio / place / 'skills' / name / 'flow.yaml'
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(text)
        return file.resolve()

    def frozen(self, folder):
        return json.loads((folder / 'runner/run.yaml').read_text())

    def test_resolve_the_definition_of_the_workspace_wins_and_its_gate_holds(self):
        # The fifth reader's probe: the shared skill flow was taken, the gate of the local one was gone, and the run ended done.
        shared = self.define('source', 'same-skill', self.spec('same-skill', 'global-step'))
        local = self.define('cedar-shop', 'same-skill', self.spec('same-skill', 'workspace-step', gate=True))
        output = self.flow('run', 'same-skill', '--workspace', 'cedar-shop')
        folder = self.run_folder('same-skill')
        info = self.frozen(folder)
        self.assertEqual(list(info['definition']['graph']), ['workspace-step'])
        self.assertEqual((info['definition_path'], info['overrides']), (str(local), [str(shared)]))
        self.assertEqual(info['definition_sha256'], hashlib.sha256(local.read_bytes()).hexdigest())
        self.assertIn('Definition: ' + str(local) + ' (workspace skill of cedar-shop)', output)
        self.assertIn('Local definition overrides shared: ' + str(shared), output)
        output = self.step(folder, 'workspace-step.md', 'done by the worker\n')
        self.assertIn('State: waits for avery', output)
        self.assertFalse((folder / 'runner/end.json').exists())
        self.assertIn('Local definition overrides shared: ' + str(shared), self.flow('status', folder.name))

    def test_resolve_without_a_workspace_the_shared_definition_is_taken(self):
        shared = self.define('source', 'same-skill', self.spec('same-skill', 'global-step'))
        self.define('cedar-shop', 'same-skill', self.spec('same-skill', 'workspace-step', gate=True))
        output = self.flow('run', 'same-skill', '--dry-run')
        self.assertIn('Valid: ' + str(shared) + ' (skill source)', output)
        self.assertNotIn('overrides', output)
        self.define('cedar-shop', 'local-only', self.spec('local-only', 'one'))
        self.assertIn('A flow of a workspace needs --workspace', self.flow('run', 'local-only', '--dry-run', expected=2))
        self.assertIn('Valid: ', self.flow('run', 'local-only', '--workspace', 'cedar-shop', '--dry-run'))

    def test_resolve_a_local_definition_that_drops_a_shared_gate_is_shown_as_an_override(self):
        shared = self.define('shelf', 'ship-it', self.spec('ship-it', 'ship', gate=True))
        local = self.define('cedar-shop', 'ship-it', self.spec('ship-it', 'ship'))
        output = self.flow('run', 'ship-it', '--workspace', 'cedar-shop', '--dry-run')
        self.assertIn('Valid: ' + str(local), output)
        self.assertIn('Local definition overrides shared: ' + str(shared), output)
        listing = self.flow('status')
        self.assertIn('local definition overrides shared: ' + str(shared), listing)
        self.assertIn('overridden in the workspace cedar-shop', listing)
        rows = {(row['source'], row['workspace']): row for row in json.loads(self.flow('status', '--json'))['flows'] if row['flow'] == 'ship-it'}
        self.assertEqual(rows[('workspace skill', 'cedar-shop')]['gates'], [])
        self.assertEqual(rows[('shelf skill', None)]['gates'], ['catalog'])

    def test_resolve_one_name_in_two_shared_places_with_different_text_is_refused(self):
        first = self.define('workflows', 'twice', self.spec('twice', 'one', kind='workflow'))
        second = self.define('shelf', 'twice', self.spec('twice', 'two', gate=True))
        output = self.flow('run', 'twice', expected=2)
        self.assertIn('is defined in more than one place of one level, and the files differ', output)
        self.assertIn(str(first), output)
        self.assertIn(str(second), output)
        self.assertEqual(list((self.home / 'runs').iterdir()), [])
        self.assertIn('REFUSED: flow twice is defined in more than one place', self.flow('status'))
        # the path of one of them says which one is meant
        self.assertIn('Valid: ' + str(second) + ' (shelf skill)', self.flow('run', str(second), '--dry-run'))

    def test_resolve_the_shelf_and_the_source_with_the_same_text_are_one_definition(self):
        text = self.spec('shipped', 'one')
        shelf = self.define('shelf', 'shipped', text)
        source = self.define('source', 'shipped', text)
        self.assertIn('Valid: ' + str(shelf) + ' (shelf skill)', self.flow('run', 'shipped', '--dry-run'))
        self.assertIn('same text as ' + str(shelf), self.flow('status'))
        two_local = self.define('cedar-shop', 'shipped', text)
        self.assertIn('Valid: ' + str(two_local), self.flow('run', 'shipped', '--workspace', 'cedar-shop', '--dry-run'))

    def test_resolve_a_flow_given_by_its_path(self):
        shared = self.define('source', 'same-skill', self.spec('same-skill', 'global-step'))
        local = self.define('cedar-shop', 'same-skill', self.spec('same-skill', 'workspace-step', gate=True))
        output = self.flow('run', str(shared), '--workspace', 'cedar-shop', '--dry-run')
        self.assertIn('Valid: ' + str(shared) + ' (skill source)', output)
        self.assertNotIn('overrides', output)
        self.flow('run', str(local))
        info = self.frozen(self.run_folder('same-skill'))
        self.assertEqual((info['definition_path'], info['workspace']), (str(local), 'cedar-shop'))
        (self.portfolio / 'oak-studio').mkdir()
        self.assertIn('that path is in the workspace cedar-shop, not in oak-studio', self.flow('run', str(local), '--workspace', 'oak-studio', '--dry-run', expected=2))
        stray = self.home / 'config/stray.yaml'
        stray.write_text(self.spec('stray', 'one'))
        self.assertIn('no flow is defined at', self.flow('run', str(stray), '--dry-run', expected=2))
        self.assertIn('Valid: ', self.flow('run', 'skillwright/skills/same-skill/flow.yaml', '--dry-run'))

    def test_resolve_a_definition_outside_the_two_homes_is_never_taken(self):
        outside = Path(self.temp.name) / 'elsewhere'
        (outside / 'evil').mkdir(parents=True)
        (outside / 'evil/flow.yaml').write_text(self.spec('evil', 'one'))
        (outside / 'loose.yaml').write_text(self.spec('loose', 'one', kind='workflow'))
        self.assertIn('the path is outside the two homes', self.flow('run', str(outside / 'evil/flow.yaml'), '--dry-run', expected=2))
        self.assertIn('the path is outside the two homes', self.flow('run', '../elsewhere/evil/flow.yaml', '--dry-run', expected=2))
        # a skill folder and a workflow file that are links out of the homes
        (self.home / 'skills/evil').symlink_to(outside / 'evil', target_is_directory=True)
        (self.home / 'skillwright/workflows/loose.yaml').symlink_to(outside / 'loose.yaml')
        for name in ('evil', 'loose'):
            self.assertIn('is only defined by a link that leaves the two homes', self.flow('run', name, '--dry-run', expected=2))
        self.assertIn('it is never taken', self.flow('status', expected=1))
        self.assertEqual(list((self.home / 'runs').iterdir()), [])

    def test_resolve_a_linked_skill_folder_inside_the_homes_is_taken_at_its_real_place(self):
        real = self.define('source', 'linked', self.spec('linked', 'one'))
        (self.home / 'skills/linked').symlink_to(real.parent, target_is_directory=True)
        output = self.flow('run', 'linked')
        self.assertIn('Definition: ' + str(real), output)
        self.assertEqual(self.frozen(self.run_folder('linked'))['definition_path'], str(real))
        rows = [row for row in json.loads(self.flow('status', '--json'))['flows'] if row['flow'] == 'linked']
        self.assertEqual(len(rows), 1)

    def test_resolve_a_folder_with_other_letter_case_is_not_the_name(self):
        self.define('shelf', 'Same-Skill', self.spec('Same-Skill', 'one'))
        self.assertIn('no flow named same-skill', self.flow('run', 'same-skill', '--dry-run', expected=2))
        self.assertIn('a flow name has lowercase letters', self.flow('run', 'Same-Skill', '--dry-run', expected=2))
        self.assertIn('the name must have lowercase letters, digits, and dashes: Same-Skill', self.flow('status', expected=1))

    def test_resolve_a_definition_that_changes_after_the_start_does_not_change_the_run(self):
        file = self.define('cedar-shop', 'kept', self.spec('kept', 'ask', gate=True))
        self.flow('run', 'kept', '--workspace', 'cedar-shop')
        folder = self.run_folder('kept')
        file.write_text(self.spec('kept', 'ask'))       # the gate is taken out of the file after the start
        output = self.step(folder, 'ask.md', 'One ask.\n')
        self.assertIn('State: waits for avery', output)
        self.assertIn('The definition file changed after the start. This run uses its frozen copy.', output)
        file.unlink()
        self.assertIn('The definition file is gone. This run uses its frozen copy.', self.flow('status', folder.name))
        self.assertEqual(self.states(folder)[0], 'waits for avery')
        info = self.frozen(folder)
        info['definition_path'] = str(self.home / 'skills/other/flow.yaml')
        (folder / 'runner/run.yaml').write_text(json.dumps(info))
        self.assertIn('run.yaml is not the file this run started with', self.flow('status', folder.name, expected=1))

    def test_resolve_status_lists_every_place_a_run_can_take_a_flow_from(self):
        # The fifth reader: status left out a shelf flow and every workspace definition.
        made = {('shelf skill', None): self.define('shelf', 'shelf-only', self.spec('shelf-only', 'one')),
                ('small-talk skill', None): self.define('small-talk', 'talk-only', self.spec('talk-only', 'one')),
                ('skill source', None): self.define('source', 'source-only', self.spec('source-only', 'one')),
                ('workspace skill', 'cedar-shop'): self.define('cedar-shop', 'local-only', self.spec('local-only', 'one'))}
        rows = {(row['source'], row['workspace']): row for row in json.loads(self.flow('status', '--json'))['flows']
                if row['flow'].endswith('-only')}
        self.assertEqual({key: row['file'] for key, row in rows.items()}, {key: str(file) for key, file in made.items()})
        self.assertTrue(all(row['taken'] and row['sha256'] for row in rows.values()))
        listing = self.flow('status')
        for file in made.values():
            self.assertIn(str(file), listing)
        self.assertIn('workspace skill of cedar-shop: ', listing)

    def test_resolve_run_and_status_see_exactly_the_same_set(self):
        # Every case at once. This test fails when run accepts a flow that status does not list as taken, or the other way.
        text = self.spec('copied', 'one')
        self.define('shelf', 'copied', text)
        self.define('source', 'copied', text)
        self.define('workflows', 'differs', self.spec('differs', 'one', kind='workflow'))
        self.define('small-talk', 'differs', self.spec('differs', 'two'))
        self.define('source', 'both', self.spec('both', 'shared-step'))
        self.define('cedar-shop', 'both', self.spec('both', 'local-step', gate=True))
        self.define('cedar-shop', 'local-only', self.spec('local-only', 'one'))
        self.define('shelf', 'broken', 'version: 2\nflow: broken\n')
        self.define('shelf', 'Upper', self.spec('Upper', 'one'))
        (self.portfolio / 'oak-studio/skills').mkdir(parents=True)
        self.define('oak-studio', 'both', self.spec('both', 'oak-step'))
        self.same_set(12)

    def same_set(self, count, status_exit=1):
        """For every definition status lists and every place a run can be asked from: run takes the file exactly when status says so."""
        rows = json.loads(self.flow('status', '--json', expected=status_exit))['flows']
        if count is not None:
            self.assertEqual(len(rows), count, [(row['flow'], row['file']) for row in rows])
        contexts = [None] + sorted(p.name for p in self.portfolio.iterdir() if p.is_dir())
        for row in rows:
            self.assertEqual(row['taken'], bool(row['runs_in']))
            for context in contexts:
                words = ['--workspace', context] if context else []
                words += ['--input', 'listing=x'] if row['flow'] == 'operate-amazon' else []
                words += ['--input', 'product=x'] if row['flow'] == 'produce-ugc-ads' else []
                result = subprocess.run([PYTHON, '-B', str(self.home / 'work/flow.py'), 'run', row['flow'], '--dry-run'] + words,
                                        cwd=str(self.home), env=self.env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                self.assertNotIn('Traceback', result.stdout)
                took = result.returncode == 0 and row['real'] is not None and ('Valid: ' + row['real'] + ' ') in result.stdout
                self.assertEqual(took, (context or 'shared') in row['runs_in'],
                                 (row['flow'], row['file'], context, row['runs_in'], row['note'], result.stdout[:300]))
        # a name that status does not list is not accepted anywhere
        for context in contexts:
            words = ['--workspace', context] if context else []
            self.assertNotIn('Valid: ', self.flow('run', 'nothing-here', '--dry-run', *words, expected=2))
        return rows

    # ------------------------------------------------------------ links: one real file is one definition, with every place that reaches it

    def link_skill(self, workspace, name, target_folder):
        link = self.portfolio / workspace / 'skills' / name
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(target_folder, target_is_directory=True)
        return link / 'flow.yaml'

    def shared_and_linked(self):
        real = self.define('source', 'shared-task', self.spec('shared-task', 'prepare'))
        links = {ws: self.link_skill(ws, 'shared-task', real.parent) for ws in ('cedar-shop', 'oak-studio')}
        return real, links

    def test_links_a_shared_flow_linked_into_two_workspaces_is_one_definition(self):
        # The sixth reader's probe P1: status listed only cedar-shop; the shared name was refused.
        real, links = self.shared_and_linked()
        rows = [row for row in json.loads(self.flow('status', '--json'))['flows'] if row['flow'] == 'shared-task']
        self.assertEqual(len(rows), 1)
        (row,) = rows
        self.assertEqual((row['file'], row['real'], row['source'], row['workspace']), (str(real), str(real), 'skill source', None))
        self.assertEqual(row['runs_in'], ['shared', 'cedar-shop', 'oak-studio'])
        self.assertEqual(sorted(place['file'] for place in row['places']), sorted([str(real)] + [str(link) for link in links.values()]))
        listing = self.flow('status')
        self.assertEqual(listing.count('shared-task (flow)'), 1)
        self.assertIn('also at: workspace skill of oak-studio: ' + str(links['oak-studio']), listing)
        self.assertIn('runs in: shared, cedar-shop, oak-studio', listing)
        self.assertNotIn('overrides shared', listing)

    def test_links_a_linked_shared_flow_runs_by_name_from_every_place(self):
        real, links = self.shared_and_linked()
        shared = self.flow('run', 'shared-task', '--dry-run')
        self.assertIn('Valid: ' + str(real) + ' (skill source)', shared)
        self.assertIn('Workspace: none (a shared run)', shared)
        for workspace in ('cedar-shop', 'oak-studio'):
            output = self.flow('run', 'shared-task', '--workspace', workspace, '--dry-run')
            self.assertIn('Valid: ' + str(real) + ' (workspace skill of ' + workspace + ', a link to ' + str(real) + ')', output)
            self.assertIn('Workspace: ' + workspace, output)
            self.assertNotIn('overrides shared', output)

    def test_links_an_explicit_shared_path_gives_a_shared_run_unless_a_workspace_is_named(self):
        # P1: the shared path started a run in cedar-shop with no workspace argument.
        real, links = self.shared_and_linked()
        output = self.flow('run', str(real))
        info = self.frozen(self.run_folder('shared-task'))
        self.assertIsNone(info['workspace'])
        self.assertEqual((info['definition_path'], info['definition_source']), (str(real), 'skill source'))
        self.assertIn('Workspace: none (a shared run)', output)
        output = self.flow('run', str(real), '--workspace', 'oak-studio')
        self.assertEqual(self.frozen(self.run_folder('shared-task-2'))['workspace'], 'oak-studio')
        self.assertIn('Workspace: oak-studio', output)

    def test_links_a_path_inside_a_workspace_names_that_workspace_and_no_other(self):
        real, links = self.shared_and_linked()
        self.flow('run', str(links['oak-studio']))
        info = self.frozen(self.run_folder('shared-task'))
        self.assertEqual((info['workspace'], info['definition_path']), ('oak-studio', str(real)))
        self.assertIn('a link to ' + str(real), info['definition_source'])
        output = self.flow('run', str(links['oak-studio']), '--workspace', 'cedar-shop', '--dry-run', expected=2)
        self.assertIn('that path is in the workspace oak-studio, not in cedar-shop', output)

    def test_links_in_every_direction_are_one_definition(self):
        # the shelf links to a skill of a workspace; one workspace links to a skill of another
        local = self.define('cedar-shop', 'made-here', self.spec('made-here', 'one'))
        (self.home / 'skills/made-here').symlink_to(local.parent, target_is_directory=True)
        self.link_skill('oak-studio', 'made-here', local.parent)
        rows = [row for row in json.loads(self.flow('status', '--json'))['flows'] if row['flow'] == 'made-here']
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]['real'], rows[0]['runs_in'], len(rows[0]['places'])), (str(local), ['shared', 'cedar-shop', 'oak-studio'], 3))
        for words in ([], ['--workspace', 'cedar-shop'], ['--workspace', 'oak-studio']):
            output = self.flow('run', 'made-here', '--dry-run', *words)
            self.assertIn('Valid: ' + str(local) + ' ', output)
            self.assertNotIn('overrides', output)

    def test_links_a_loop_and_a_missing_target_are_reported_and_stop_nothing(self):
        skills = self.home / 'skills'
        (skills / 'loop-a').symlink_to(skills / 'loop-b', target_is_directory=True)
        (skills / 'loop-b').symlink_to(skills / 'loop-a', target_is_directory=True)
        (skills / 'gone-folder').symlink_to(skills / 'not-there', target_is_directory=True)
        (skills / 'gone-file').mkdir()
        (skills / 'gone-file/flow.yaml').symlink_to(skills / 'not-there/flow.yaml')
        (skills / 'self-file').mkdir()
        (skills / 'self-file/flow.yaml').symlink_to(skills / 'self-file/flow.yaml')
        (self.home / 'skillwright/workflows/dangling.yaml').symlink_to(self.home / 'not-there.yaml')
        good = self.define('shelf', 'good', self.spec('good', 'one'))
        self.assertIn('Valid: ' + str(good), self.flow('run', 'good', '--dry-run'))
        self.assertIn('Valid: ', self.flow('run', 'operate-amazon', '--dry-run', '--input', 'listing=x'))
        rows = {row['flow']: row for row in json.loads(self.flow('status', '--json', expected=1))['flows']}
        for name in ('loop-a', 'loop-b', 'gone-folder', 'gone-file', 'self-file', 'dangling'):
            self.assertEqual((rows[name]['valid'], rows[name]['taken'], rows[name]['real']), (False, False, None), name)
            self.assertIn('leads nowhere, or a link loop', rows[name]['problems'][0])
            self.assertIn('is only defined by a link', self.flow('run', name, '--dry-run', expected=2))
        self.assertTrue(rows['good']['taken'])
        self.assertNotIn('Traceback', self.flow('status', expected=1))

    def test_links_a_linked_skill_folder_with_no_flow_is_not_a_flow(self):
        plain = self.home / 'skillwright/skills/plain'
        plain.mkdir(parents=True)
        (plain / 'SKILL.md').write_text('# plain\n')
        self.link_skill('cedar-shop', 'plain', plain)
        self.assertNotIn('plain', [row['flow'] for row in json.loads(self.flow('status', '--json'))['flows']])

    def test_links_two_workspaces_with_the_same_local_name_each_run_their_own(self):
        cedar = self.define('cedar-shop', 'pack', self.spec('pack', 'cedar-step', gate=True))
        oak = self.define('oak-studio', 'pack', self.spec('pack', 'oak-step'))
        self.assertIn('Valid: ' + str(cedar), self.flow('run', 'pack', '--workspace', 'cedar-shop', '--dry-run'))
        self.assertIn('Valid: ' + str(oak), self.flow('run', 'pack', '--workspace', 'oak-studio', '--dry-run'))
        self.assertIn('A flow of a workspace needs --workspace', self.flow('run', 'pack', '--dry-run', expected=2))
        rows = {row['workspace']: row for row in json.loads(self.flow('status', '--json'))['flows'] if row['flow'] == 'pack'}
        self.assertEqual({ws: row['runs_in'] for ws, row in rows.items()}, {'cedar-shop': ['cedar-shop'], 'oak-studio': ['oak-studio']})
        self.assertEqual((rows['cedar-shop']['gates'], rows['oak-studio']['gates']), (['catalog'], []))

    def test_links_one_real_file_under_two_names_is_valid_under_its_own_name_only(self):
        alpha = self.define('shelf', 'alpha', self.spec('alpha', 'one'))
        (self.home / 'skills/beta').symlink_to(alpha.parent, target_is_directory=True)
        self.assertIn('Valid: ' + str(alpha), self.flow('run', 'alpha', '--dry-run'))
        output = self.flow('run', 'beta', '--dry-run', expected=2)
        self.assertIn('flow must equal the file name: beta', output)
        rows = {row['flow']: row for row in json.loads(self.flow('status', '--json', expected=1))['flows'] if row['flow'] in ('alpha', 'beta')}
        self.assertEqual((rows['alpha']['valid'], rows['alpha']['taken'], rows['beta']['valid'], rows['beta']['taken']), (True, True, False, False))

    def test_links_run_and_status_see_the_same_set_with_links_of_every_kind(self):
        real, links = self.shared_and_linked()
        local = self.define('cedar-shop', 'made-here', self.spec('made-here', 'one'))
        (self.home / 'skills/made-here').symlink_to(local.parent, target_is_directory=True)
        self.define('cedar-shop', 'pack', self.spec('pack', 'cedar-step', gate=True))
        self.define('oak-studio', 'pack', self.spec('pack', 'oak-step'))
        alpha = self.define('shelf', 'alpha', self.spec('alpha', 'one'))
        (self.home / 'skills/beta').symlink_to(alpha.parent, target_is_directory=True)
        (self.home / 'skills/gone').symlink_to(self.home / 'skills/not-there', target_is_directory=True)
        self.define('source', 'both', self.spec('both', 'shared-step'))
        self.define('oak-studio', 'both', self.spec('both', 'oak-step', gate=True))
        self.write_flow('malformed', 'version: 1\nflow: malformed\npurpose: "x"\nmembers: {worker: {seat: mercer}}\ngraph:\n'
                        '  prepare: {member: worker, needs: [[other]], done_when: {file: prepare.md}}\n')
        rows = self.same_set(None)
        every = ('shared', 'cedar-shop', 'oak-studio')
        self.assertEqual(sorted((row['flow'], len(row['places']), tuple(row['runs_in'])) for row in rows), [
            ('alpha', 1, every), ('beta', 1, ()), ('both', 1, ('oak-studio',)), ('both', 1, ('shared', 'cedar-shop')), ('gone', 1, ()),
            ('made-here', 2, every), ('malformed', 1, ()), ('operate-amazon', 1, every), ('pack', 1, ('cedar-shop',)),
            ('pack', 1, ('oak-studio',)), ('produce-ugc-ads', 1, every), ('shared-task', 3, every)])

    # ------------------------------------------------------------ a file that is not a flow is a problem of that file only

    BAD_FILES = {
        'needs-a-list-in-a-list': 'version: 1\nflow: NAME\npurpose: "x"\nmembers: {worker: {seat: mercer}}\ngraph:\n  prepare: {member: worker, needs: [[other]], done_when: {file: prepare.md}}\n',
        'member-is-a-list': 'version: 1\nflow: NAME\npurpose: "x"\nmembers: {worker: {seat: mercer}}\ngraph:\n  prepare: {member: [worker], done_when: {file: prepare.md}}\n',
        'graph-is-a-list': 'version: 1\nflow: NAME\npurpose: "x"\ngraph: [one, two]\n',
        'members-is-a-list': 'version: 1\nflow: NAME\npurpose: "x"\nmembers: [worker]\ngraph:\n  prepare: {member: worker, done_when: {file: prepare.md}}\n',
        'step-is-a-word': 'version: 1\nflow: NAME\npurpose: "x"\nmembers: {worker: {seat: mercer}}\ngraph:\n  prepare: later\n',
        'loop-is-a-word': 'version: 1\nflow: NAME\npurpose: "x"\nmembers: {worker: {seat: mercer}}\ngraph:\n  prepare: {member: worker, done_when: {file: prepare.md}}\nloop: again\n',
        'repair-on-is-a-list': 'version: 1\nflow: NAME\npurpose: "x"\nmembers: {worker: {seat: mercer}}\ngraph:\n  prepare: {member: worker, verdict: true, done_when: {file: prepare.md}}\nloop: {repair: {on: [prepare], repeat: [[prepare]], max_rounds: 1}}\n',
        'gate-is-a-map': 'version: 1\nflow: NAME\npurpose: "x"\nmembers: {worker: {seat: mercer}}\ngraph:\n  prepare: {member: worker, gate: {a: b}, skill: [x], done_when: {file: prepare.md}}\n',
        'file-is-a-list': 'version: 1\nflow: NAME\npurpose: "x"\nmembers: {worker: {seat: mercer}}\ngraph:\n  prepare: {member: worker, done_when: {file: [a, b]}}\n',
        'top-is-a-list': '- one\n- two\n',
        'not-yaml': '{{{{ this is : not [ a file\n\t\x00\x01',
        'empty': '',
        'key-twice': 'version: 1\nversion: 1\nflow: NAME\n',
    }

    def test_malformed_each_bad_file_is_listed_for_itself_and_breaks_no_other_flow(self):
        # The sixth reader's probe P2: needs: [[other]] in one file made a dry run of operate-amazon crash.
        for name, text in self.BAD_FILES.items():
            self.write_flow(name, text.replace('NAME', name))
        output = self.flow('run', 'operate-amazon', '--dry-run', '--input', 'listing=x')
        self.assertIn('Valid: ', output)
        self.assertNotIn('Traceback', output)
        listing = self.flow('status', expected=1)
        self.assertNotIn('Traceback', listing)
        rows = {row['flow']: row for row in json.loads(self.flow('status', '--json', expected=1))['flows']}
        for name in self.BAD_FILES:
            self.assertEqual((rows[name]['valid'], rows[name]['taken']), (False, False), name)
            self.assertTrue(rows[name]['problems'], name)
            refused = self.flow('run', name, '--dry-run', expected=2)
            self.assertIn('is not valid', refused, name)
            self.assertNotIn('Traceback', refused, name)
        self.assertEqual((rows['operate-amazon']['valid'], rows['produce-ugc-ads']['valid']), (True, True))
        self.assertIn('needs must be a list of step names', ' '.join(rows['needs-a-list-in-a-list']['problems']))
        self.assertEqual(list((self.home / 'runs').iterdir()), [])

    def test_malformed_a_bad_file_beside_a_run_in_progress_changes_nothing_for_the_run(self):
        folder, _ = self.start_amazon()
        self.write_flow('malformed', self.BAD_FILES['needs-a-list-in-a-list'].replace('NAME', 'malformed'))
        self.write_flow('not-yaml', self.BAD_FILES['not-yaml'])
        output = self.step(folder, 'audit.md', 'findings\n')
        self.assertIn('NEXT  check', output)
        self.assertIn(folder.name + ': running', self.flow('status', expected=1))


    def test_malformed_a_place_nobody_may_read_is_reported_and_stops_nothing(self):
        closed = self.home / 'skills/closed-folder'
        closed.mkdir()
        (closed / 'flow.yaml').write_text(self.spec('closed-folder', 'one'))
        file = self.define('shelf', 'closed-file', self.spec('closed-file', 'one'))
        (self.home / 'skillwright/workflows/not-text.yaml').write_bytes(b'\xff\xfe\x00flow: \x80\x81')
        closed.chmod(0)
        file.chmod(0)
        self.addCleanup(lambda: (closed.chmod(0o700), file.chmod(0o600)))
        output = self.flow('run', 'operate-amazon', '--dry-run', '--input', 'listing=x')
        self.assertIn('Valid: ', output)
        rows = {row['flow']: row for row in json.loads(self.flow('status', '--json', expected=1))['flows']}
        for name in ('closed-folder', 'closed-file', 'not-text'):
            self.assertEqual((rows[name]['valid'], rows[name]['taken']), (False, False), name)
            refused = self.flow('run', name, '--dry-run', expected=2)
            self.assertNotIn('Traceback', refused)
        self.assertIn('the place can not be read', rows['closed-folder']['problems'][0])
        self.assertNotIn('Traceback', self.flow('status', expected=1))

    def test_links_a_file_link_a_chain_of_links_and_a_linked_skills_folder_are_one_definition(self):
        real = self.define('source', 'chained', self.spec('chained', 'one'))
        # a link to the file alone; a link to a link to the folder; the whole skills folder of a workspace as a link
        (self.home / 'skills/chained').mkdir()
        (self.home / 'skills/chained/flow.yaml').symlink_to(real)
        middle = Path(self.temp.name).resolve() / 'system/middle'
        middle.symlink_to(real.parent, target_is_directory=True)
        self.link_skill('cedar-shop', 'chained', middle)
        (self.portfolio / 'oak-studio').mkdir()
        (self.portfolio / 'oak-studio/skills').symlink_to(self.portfolio / 'cedar-shop/skills', target_is_directory=True)
        rows = [row for row in json.loads(self.flow('status', '--json'))['flows'] if row['flow'] == 'chained']
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]['real'], len(rows[0]['places']), rows[0]['runs_in']), (str(real), 4, ['shared', 'cedar-shop', 'oak-studio']))
        for words in ([], ['--workspace', 'cedar-shop'], ['--workspace', 'oak-studio']):
            output = self.flow('run', 'chained', '--dry-run', *words)
            self.assertIn('Valid: ' + str(real) + ' ', output)
            self.assertNotIn('overrides', output)

    def test_links_two_names_of_one_file_on_disk_in_two_shared_places_are_one_definition(self):
        first = self.define('shelf', 'twin', self.spec('twin', 'one'))
        (self.home / 'skillwright/skills/twin').mkdir(parents=True)
        os.link(str(first), str(self.home / 'skillwright/skills/twin/flow.yaml'))
        self.assertIn('Valid: ' + str(first), self.flow('run', 'twin', '--dry-run'))
        rows = [row for row in json.loads(self.flow('status', '--json'))['flows'] if row['flow'] == 'twin']
        self.assertEqual([(row['taken'], row['note']) for row in rows],
                         [(True, ''), (False, 'same text as ' + str(first))])

    def test_links_a_path_that_is_not_a_place_is_refused_and_names_the_places(self):
        local = self.define('cedar-shop', 'made-here', self.spec('made-here', 'one'))
        (self.portfolio / 'cedar-shop/.agents').mkdir()
        (self.portfolio / 'cedar-shop/.agents/skills').symlink_to(self.portfolio / 'cedar-shop/skills', target_is_directory=True)
        side = self.portfolio / 'cedar-shop/.agents/skills/made-here/flow.yaml'
        output = self.flow('run', str(side), '--dry-run', expected=2)
        self.assertIn('the path is not a place of a flow. Its file is reached from: ' + str(local), output)
        self.assertIn('Workspace: cedar-shop', self.flow('run', str(side), '--workspace', 'cedar-shop', '--dry-run'))
        self.assertEqual(list((self.home / 'runs').iterdir()), [])


    def test_links_a_home_reached_through_a_link_is_the_same_home(self):
        real, links = self.shared_and_linked()
        side = Path(self.temp.name).resolve() / 'side'
        side.mkdir()
        (side / 'sys').symlink_to(self.home, target_is_directory=True)
        (side / 'port').symlink_to(self.portfolio, target_is_directory=True)
        output = self.flow('run', str(side / 'sys/skillwright/skills/shared-task/flow.yaml'), '--dry-run')
        self.assertIn('Valid: ' + str(real) + ' (skill source)', output)
        self.assertIn('Workspace: none (a shared run)', output)
        output = self.flow('run', str(side / 'port/oak-studio/skills/shared-task/flow.yaml'), '--dry-run')
        self.assertIn('Workspace: oak-studio', output)
        output = self.flow('run', str(side / 'port/oak-studio/skills/shared-task/flow.yaml'), '--workspace', 'cedar-shop', '--dry-run', expected=2)
        self.assertIn('that path is in the workspace oak-studio, not in cedar-shop', output)

    def test_links_a_link_to_a_shared_file_overrides_no_copy_of_the_same_text(self):
        # the shelf is a copy of the source; a workspace links to the source: that is the shared definition, not an override
        text = self.spec('copied', 'one')
        source = self.define('source', 'copied', text)
        shelf = self.define('shelf', 'copied', text)
        self.link_skill('cedar-shop', 'copied', source.parent)
        output = self.flow('run', 'copied', '--workspace', 'cedar-shop', '--dry-run')
        self.assertIn('Valid: ' + str(source) + ' ', output)
        self.assertNotIn('overrides', output)
        self.assertNotIn('overrid', self.flow('status'))
        # a file of the workspace itself is an override, and both sides say so
        (self.portfolio / 'oak-studio').mkdir()
        own = self.define('oak-studio', 'copied', self.spec('copied', 'oak-step'))
        output = self.flow('run', 'copied', '--workspace', 'oak-studio', '--dry-run')
        self.assertIn('Valid: ' + str(own) + ' ', output)
        self.assertIn('Local definition overrides shared: ' + str(shelf), output)
        listing = self.flow('status')
        self.assertIn('local definition overrides shared: ', listing)
        self.assertIn('overridden in the workspace oak-studio', listing)


# ====================================================================================================================
# Round 8. Generated tests of the two rules: fail closed, and the strict schema.
# They read the table SCHEMA and the list RULES of flow.py and make one case for each key, each wrong type, each place.
# They make some thousand calls, so flow.py runs inside this process (main(argv)). It is the same file the tests above start.

def load_flow():
    """work/flow.py as a module of this process. Loading it changes nothing in the environment of the tests."""
    saved, path = os.environ.get('FOXRUN_HOME'), list(sys.path)
    spec = importlib.util.spec_from_file_location('flow_under_test', str(ROOT / 'work/flow.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sys.path[:] = path if str(ROOT) in path else [str(ROOT)] + path
    if saved is None:
        os.environ.pop('FOXRUN_HOME', None)
    else:
        os.environ['FOXRUN_HOME'] = saved
    return module


FLOW = load_flow()
CHANGE = ['python3', 'tools/change.py']
# A definition with every key of the schema. Its first step is code with no gate: if a wrong file started a run, code would run.
FULL = {
    'version': 1, 'flow': 'full', 'kind': 'workflow', 'purpose': 'Hold every key of the schema.',
    'inputs': {'thing': {'required': False, 'what': 'One thing.'}}, 'lead': 'worker', 'worker_minutes': 30,
    'members': {'worker': {'seat': 'mercer', 'what': 'The worker.', 'voice': True, 'runtime': 'codex', 'model': 'test-model', 'tier': None, 'effort': 'high',
                           'access': 'read'}},
    'graph': {
        'change': {'run': CHANGE, 'needs': [], 'gate': 'production'},
        'review': {'member': 'worker', 'skill': 'log', 'needs': ['change'], 'input': ['the change'], 'output': 'One verdict.',
                   'done_when': {'file': 'review.md'}, 'verdict': True, 'gate': 'send', 'return': 'mercer'}},
    'loop': {'repair': {'on': 'review', 'repeat': ['review'], 'max_rounds': 1}},
    'rules': ['One rule.'],
}
# Where one map of each object is in FULL. A step is looked at two times: the step with a member, and the code step.
AT = {'flow': [[]], 'input': [['inputs', 'thing']], 'member': [['members', 'worker']],
      'step': [['graph', 'review'], ['graph', 'change']], 'done_when': [['graph', 'review', 'done_when']],
      'loop': [['loop']], 'repair': [['loop', 'repair']]}
# Keys with need `may` that a rule still needs in FULL: without them the file is refused (R03, R04, R05, R11).
NEEDED_BY_A_RULE = {('step', 'member'), ('step', 'run'), ('step', 'done_when'), ('step', 'verdict'), ('flow', 'members')}
# For each type of the schema: values that are NOT of that type. Written by hand; no line here comes from the validator.
# A type that is in SCHEMA and not here fails the test: a new type needs its wrong values.
MAPS = [{}, {'a': 'b'}, {'a': {'b': 1}}]
BAD = {
    'int:1..1': [None, True, False, 0, 2, -1, 1.0, 1.5, '1', '', [], [1], {}],
    'int:1..5': [None, True, 0, 6, -1, 2.5, '2', '', [], [2], {}],
    'int:1..240': [None, True, 0, 241, -1, 2.5, '30', '', [], [30], {}],
    'int:1..': [None, True, 0, -3, 1.5, '1', [], {}],
    'int': [None, True, 1.5, '0', [], {}],
    'number': [None, True, '1.5', 'now', [], {}, -1, -0.5, float('nan'), float('inf'), float('-inf')],
    'bool': [None, 0, 1, 'true', 'false', 'yes', '', [], [True], {}],
    'null': [True, 0, '', 'null', 'x', [], {}],
    'string': [None, True, 7, [], {}],
    'sentence': [None, True, 7, 1.5, '', '   ', [], ['One sentence.'], {}],
    'name': [None, True, 7, 1.5, '', ' ', 'Two Words', 'UPPER', '9', '12-34', '-a', 'a/b', 'a.b', [], ['mercer'], {}],
    'step-name': [None, True, 7, '', 'Two Words', 'UPPER', '9', [], ['review'], {}, 'ghost'],
    'null or name': [True, 7, 1.5, '', 'Two Words', '9', [], ['log'], {}],
    'null or token': [True, 7, 1.5, '', 'two words', 'a/b', [], ['T1'], {}],
    'null or folder': [True, 7, '', ' ', 'a/b', '..', '.', [], {}],
    'null or hash': [True, 7, '', 'abc', 'A' * 64, 'g' * 64, 'a' * 63, [], {}],
    'null or word:pass|fail': [True, 7, '', 'maybe', 'PASS', [], {}],
    'word:workflow|flow': [None, True, 7, '', 'squad', 'Flow', [], ['flow'], {}],
    'word:claude|codex|hermes': [None, True, 7, '', 'other', [], ['codex'], {}],
    'null or word:judgment|work|cheap|code': [True, 7, '', 'other', 'CODE', [], ['code'], {}],
    'word:low|medium|high|xhigh|max': [None, True, 7, '', 'highest', [], ['high'], {}],
    'word:read|write': [None, True, 7, '', 'admin', 'READ', [], ['read'], {}],
    'word:yes|no': [None, True, 7, '', 'maybe', 'YES', [], {}],
    'token': [None, True, 7, '', 'two words', 'a/b', [], ['gpt'], {}],
    'file': [None, True, 7, '', 'a/b.md', '../x.md', '/abs.md', 'two words.md', '.hidden', [], ['a.md'], {}],
    'hash': [None, True, 7, '', 'abc', 'A' * 64, 'g' * 64, 'a' * 63, 'a' * 65, [], {}],
    'hash or word:nothing was accepted yet': [None, True, 7, '', 'abc', 'nothing', 'A' * 64, [], {}],
    'time': [None, True, 7, 1.5, '', 'now', 'x', '2026-13-45', [], {}],
    'path': [None, True, 7, '', 'relative/path', 'a\nb', [], {}],
    'texts': [None, True, 7, '', 'x', [], [['a', 'b']], {'Bad Key': 'x'}, {'thing': 7}, {'thing': None}, {'thing': ['x']}],
    'event-name': [None, True, 7, '', 'made-up', 'RUN-START', [], {}],
    'command': [None, True, 7, '', 'python3 tools/change.py', [], ['python3'], ['tools/change.py'], ['sh', 'tools/change.py'],
                ['/usr/bin/python3', 'tools/change.py'], ['python3', ''], ['python3', ' tools/change.py'], ['python3', '/bin/sh'],
                ['python3', '../x.py'], ['python3', 'tools/../../x.py'], ['python3', '-c'], ['python3', 7], ['python3', None],
                ['python3', ['tools/change.py']], [['python3', 'tools/change.py']], {'python3': 'tools/change.py'},
                ['python3', 'tools/change.py', ''], ['python3', 'tools/change.py', 3], ['python3', 'tools/change.py', ['x']]],
    'list:sentence': [None, True, 7, 'one', {}, [7], [None], [''], ['  '], [['x']], [{}], ['fine', 7]],
    'list:step-name': [None, True, 7, 'review', '', {}, {'a': 'b'}, [7], [None], [''], [['review']], ['Two Words'], [{}], ['9']],
    'list:path': [None, True, 7, '/a/b', {}, [7], [None], [''], ['relative'], [['/a']]],
    'map:input': [None, True, 7, 'x', [], ['a']] + [{'Bad Name': {'what': 'x'}}, {'9': {'what': 'x'}}, {'thing': 'text'}, {'thing': []},
                                                    {'thing': None}, {'thing': {}}, {'thing': {'what': ''}}, {'thing': {'what': 'x', 'more': 1}}],
    'map:member': [None, True, 7, 'x', [], ['a']] + [{'Bad Name': {'seat': 'mercer'}}, {'worker': 'mercer'}, {'worker': ['mercer']},
                                                     {'worker': None}, {'worker': {}}, {'worker': {'seat': ['mercer']}}, {'worker': {'seat': 7}}],
    'map:step': [None, True, 7, 'x', [], ['a'], {}] + [{'Bad Name': {'run': CHANGE}}, {'9': {'run': CHANGE}}, {'go': 'later'},
                                                       {'go': None}, {'go': []}, {'go': {}}, {'go': {'run': CHANGE, 'more': 1}}],
    'object:loop': [None, True, 7, 'again', [], ['a'], {}, {'repiar': {'on': 'review', 'repeat': ['review'], 'max_rounds': 1}},
                    {'repair': None}, {'repair': 'x'}, {'repair': {}}],
    'object:repair': [None, True, 7, 'x', [], ['a'], {}, {'on': 'review'}, {'on': 'review', 'repeat': ['review'], 'max_rounds': 1, 'more': 1}],
    'object:done_when': [None, True, 7, 'review.md', [], ['review.md'], {}, {'file': 'review.md', 'more': 1}, {'files': 'review.md'}],
    'definition': [None, True, 7, 'x', [], {}, {'version': 1}],
}
# For each rule of RULES: changes of FULL that break that rule and no row of SCHEMA. A rule that is not here fails the test.


def change(*path_and_value):
    def do(data):
        *path, key, value = path_and_value
        spot = data
        for name in path:
            spot = spot[name]
        if value is REMOVE:
            del spot[key]
        else:
            spot[key] = value
    return do


REMOVE = object()
SECOND = {'member': 'worker', 'needs': ['review'], 'done_when': {'file': 'second.md'}}
BREAKS = {
    'R01': [change('flow', 'other')],
    'R02': [change('graph', {})],
    'R03': [change('graph', 'review', 'run', CHANGE), change('graph', 'change', 'member', 'worker'), change('graph', 'change', 'run', REMOVE)],
    'R04': [change('graph', 'review', 'member', 'nobody'), change('members', REMOVE)],
    'R05': [change('graph', 'review', 'done_when', REMOVE)],
    'R06': [change('graph', 'review', 'done_when', {'file': name}) for name in
            ('run.yaml', 'RUNNER', 'runner', 'events.jsonl', 'Lock', 'end.json', 'decisions', 'attempts', 'x.yes.md', 'x.NO.md', 'start-page.md')],
    'R07': [change('graph', 'second', dict(SECOND, done_when={'file': name})) for name in ('review.md', 'REVIEW.MD', 'Review.md')],
    'R08': [change('graph', 'change', key, value) for key, value in
            (('done_when', {'file': 'change.md'}), ('verdict', True), ('verdict', False), ('skill', 'log'), ('skill', None),
             ('input', ['x']), ('output', 'x'), ('return', 'mercer'))],
    'R09': [change('graph', 'review', 'needs', ['ghost']), change('graph', 'review', 'needs', ['review']),
            change('graph', 'review', 'needs', ['change', 'change']), change('graph', 'change', 'needs', ['change'])],
    'R10': [change('graph', 'change', 'needs', ['review'])],
    'R11': [change('loop', 'repair', 'on', 'change'), change('loop', 'repair', 'on', 'ghost'), change('graph', 'review', 'verdict', False),
            change('graph', 'review', 'verdict', REMOVE)],
    'R12': [change('loop', 'repair', 'repeat', value) for value in ([], ['ghost'], ['change'], ['review', 'review'], ['review', 'ghost'])],
    'R13': [change('members', 'worker', {'voice': True}), change('members', 'worker', {'model': 'test-model', 'effort': 'high'})],
    'R14': [change('lead', 'nobody'), change('lead', 'mercer')],
    'D01': [change('members', 'worker', 'seat', 'ghost'), change('members', 'worker', 'seat', 'linked-out'),
            change('members', 'worker', 'seat', 'a-folder'), change('members', 'other', {'seat': 'ghost'})],
    'D02': [change('graph', 'change', 'run', ['python3', 'tools/none.py']), change('graph', 'change', 'run', ['python3', 'tools/linked-out.py']),
            change('graph', 'change', 'run', ['python3', 'tools']), change('graph', 'change', 'run', ['python3', 'tools/a-folder'])],
}
# A flow that is at rest with a result that waits and a code step behind it: the next resume would accept and then run code.
RESTING = ('version: 1\nflow: resting\npurpose: "Rest before code runs."\nmembers:\n  worker: {seat: mercer}\ngraph:\n'
           '  review:\n    member: worker\n    verdict: true\n    done_when: {file: review.md}\n'
           '  first:\n    run: [python3, tools/change.py]\n    needs: [review]\n    gate: production\n'
           '  second:\n    member: worker\n    needs: [first]\n    done_when: {file: second.md}\n'
           '  third:\n    run: [python3, tools/third.py]\n    needs: [second]\n'
           'loop:\n  repair: {on: review, repeat: [review], max_rounds: 1}\n')
ASKING = ('version: 1\nflow: asking\npurpose: "A yes, then a result, then code."\nmembers:\n  worker: {seat: mercer}\ngraph:\n'
          '  ask:\n    member: worker\n    gate: send\n    done_when: {file: ask.md}\n'
          '  write:\n    member: worker\n    needs: [ask]\n    done_when: {file: write.md}\n'
          '  third:\n    run: [python3, tools/third.py]\n    needs: [write]\n')
PUBLISH = {'version': 1, 'flow': 'publish', 'purpose': 'Change one thing.', 'graph': {'change': {'run': CHANGE}}}
PLACES = {'workspace workflow': 'portfolio/cedar-shop/workflows', 'workspace skill': 'portfolio/cedar-shop/skills',
          'system workflow': 'system/skillwright/workflows', 'shelf skill': 'system/skills',
          'small-talk skill': 'system/small-talk/skills', 'skill source': 'system/skillwright/skills',
          'product workflow': 'system/skillwright/workflows/.product'}


class ClosedTests(unittest.TestCase):
    COUNTS = {}

    @classmethod
    def tearDownClass(cls):
        """Write how many cases each generated test made, when the caller asks for it."""
        if os.environ.get('FOXRUN_TEST_COUNTS'):
            Path(os.environ['FOXRUN_TEST_COUNTS']).write_text(json.dumps(cls.COUNTS, indent=2, sort_keys=True) + '\n')

    setUp = FlowTests.setUp
    flow = FlowTests.flow
    write_flow = FlowTests.write_flow
    bytes_of = FlowTests.bytes_of

    def call(self, *args):
        """flow.py main(argv) in this process: (exit code, everything it printed). Exit code 4 and a Traceback always fail the test."""
        saved = {key: os.environ.get(key) for key in ('FOXRUN_HOME', 'FOXRUN_PORTFOLIO', 'FOXRUN_SEAT', 'FOXRUN_STATE')}
        for key in saved:
            os.environ.pop(key, None)
        os.environ.update(FOXRUN_HOME=str(self.home), FOXRUN_PORTFOLIO=str(self.portfolio))
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                try:
                    code = FLOW.main([str(word) for word in args])
                except SystemExit as stop:
                    code = stop.code
        finally:
            for key, value in saved.items():
                os.environ.pop(key, None)
                if value is not None:
                    os.environ[key] = value
        text = out.getvalue()
        self.assertNotEqual(code, 4, text)
        self.assertNotIn('internal error', text)
        self.assertNotIn('Traceback', text)
        return code, text

    def runs(self):
        return sorted(p.name for p in (self.home / 'runs').iterdir())

    def define(self, data, name='full'):
        (self.home / 'skillwright/workflows' / (name + '.yaml')).write_text(json.dumps(data))

    def refused(self, data, label, name='full'):
        """A definition that must be refused: status says not valid, no call starts a run, no code runs, no folder is made."""
        self.define(data, name)
        with self.subTest(case=str(label)[:150]):
            code, text = self.call('status', '--json')
            row = [row for row in json.loads(text)['flows'] if row['flow'] == name]
            self.assertEqual((code, [r['valid'] for r in row], [r['taken'] for r in row]), (1, [False], [False]), text[:400])
            self.assertTrue(row[0]['problems'])
            for words in (['--dry-run'], []):
                code, text = self.call('run', name, *words)
                self.assertEqual(code, 2, text)
                self.assertIn('FAIL flow run', text)
            self.assertEqual(self.runs(), [])
            self.assertFalse(list(self.home.rglob('changed')))

    def accepted(self, data, label, name='full'):
        self.define(data, name)
        with self.subTest(case=str(label)[:150]):
            code, text = self.call('run', name, '--dry-run')
            self.assertEqual(code, 0, text)
            self.assertEqual(self.runs(), [])

    # ------------------------------------------------------------ the schema: every key of a definition

    def test_schema_the_file_with_every_key_is_valid_and_the_table_names_each_of_its_keys(self):
        self.accepted(json.loads(json.dumps(FULL)), 'the whole file')
        for kind, spots in AT.items():
            for spot in spots:
                here = FULL
                for name in spot:
                    here = here[name]
                listed = {row[1] for row in FLOW.SCHEMA if row[0] == kind}
                self.assertLessEqual(set(here), listed, kind)
        self.assertEqual({row[1] for row in FLOW.SCHEMA if row[0] == 'step'}, set(FULL['graph']['review']) | set(FULL['graph']['change']))
        for kind in ('flow', 'input', 'member', 'done_when', 'loop', 'repair'):
            here = FULL
            for name in AT[kind][0]:
                here = here[name]
            self.assertEqual({row[1] for row in FLOW.SCHEMA if row[0] == kind}, set(here), kind)
        for row in FLOW.SCHEMA:
            self.assertEqual(len(row), 5)
            self.assertIn(row[2], ('must', 'may'))
            self.assertIn(row[3], BAD, 'the test has no wrong values for the type ' + row[3])
        self.assertEqual({row[0] for row in FLOW.SCHEMA}, set(AT) | {'run', 'event', 'decision'} | set(FLOW.EVENTS))

    def test_schema_each_key_of_a_definition_refuses_each_wrong_type_a_missing_value_and_an_unknown_key(self):
        cases = 0
        for kind, key, need, type_, _ in FLOW.SCHEMA:
            for spot in AT.get(kind, ()):
                data = json.loads(json.dumps(FULL))
                here = data
                for name in spot:
                    here = here[name]
                if key not in here:
                    continue                # the key belongs to the other kind of step
                for value in BAD[type_]:
                    data = json.loads(json.dumps(FULL))
                    here = data
                    for name in spot:
                        here = here[name]
                    here[key] = value
                    self.refused(data, (kind, key, 'wrong type', value))
                    cases += 1
                data = json.loads(json.dumps(FULL))
                here = data
                for name in spot:
                    here = here[name]
                del here[key]
                if need == 'must' or (kind, key) in NEEDED_BY_A_RULE:
                    self.refused(data, (kind, key, 'missing'))
                else:
                    self.accepted(data, (kind, key, 'left out: the default is taken'))
                cases += 1
        for kind, spots in AT.items():
            for spot in spots:
                for extra in ('extra', 'Seat', 'needs ', 'gates', '1'):
                    data = json.loads(json.dumps(FULL))
                    here = data
                    for name in spot:
                        here = here[name]
                    here[extra] = 'x'
                    self.refused(data, (kind, 'unknown key', extra))
                    cases += 1
        self.assertGreater(cases, 400)
        self.COUNTS['definition keys: wrong type, missing, unknown key'] = cases

    def test_schema_a_key_that_is_not_a_text_and_a_key_written_two_times_are_refused(self):
        for label, text in (('a number as a step name', 'version: 1\nflow: full\npurpose: "x"\ngraph:\n  1:\n    run: [python3, tools/change.py]\n'),
                            ('a number as a key of a step', 'version: 1\nflow: full\npurpose: "x"\ngraph:\n  go:\n    run: [python3, tools/change.py]\n    7: x\n'),
                            ('true as a key', 'version: 1\nflow: full\npurpose: "x"\ntrue: x\ngraph:\n  go:\n    run: [python3, tools/change.py]\n'),
                            ('a key two times', 'version: 1\nflow: full\npurpose: "x"\ngraph:\n  go:\n    run: [python3, tools/change.py]\n    run: [python3, tools/change.py]\n'),
                            ('a step two times', 'version: 1\nflow: full\npurpose: "x"\ngraph:\n  go:\n    run: [python3, tools/change.py]\n  go:\n    run: [python3, tools/change.py]\n'),
                            ('a list at the top', '- version: 1\n'), ('no text', ''), ('one word', 'flow\n'), ('JSON null', 'null\n')):
            (self.home / 'skillwright/workflows/full.yaml').write_text(text)
            with self.subTest(case=label):
                code, out = self.call('run', 'full')
                self.assertEqual(code, 2, out)
                self.assertEqual(self.runs(), [])
                self.assertEqual(self.call('status')[0], 1)

    def test_schema_each_rule_has_a_file_that_breaks_it_and_each_such_file_is_refused(self):
        self.assertEqual(set(BREAKS), {rule[0] for rule in FLOW.RULES})
        outside = Path(self.temp.name).resolve() / 'outside'
        outside.mkdir()
        (outside / 'seat.md').write_text('# a seat outside the homes\n')
        (outside / 'script.py').write_text("import os, pathlib\npathlib.Path(os.environ['FOXRUN_RUN_DIR'], 'changed').write_text('x')\n")
        (self.home / 'agents/linked-out.md').symlink_to(outside / 'seat.md')
        (self.home / 'agents/a-folder.md').mkdir()
        (self.home / 'tools/linked-out.py').symlink_to(outside / 'script.py')
        (self.home / 'tools/a-folder').mkdir()
        (self.portfolio / 'oak-studio/team').mkdir(parents=True)
        (self.portfolio / 'oak-studio/skills').mkdir()
        (self.portfolio / 'oak-studio/team/ghost.md').write_text('# a seat of another workspace\n')
        cases = 0
        for rule, ways in sorted(BREAKS.items()):
            for number, way in enumerate(ways, 1):
                data = json.loads(json.dumps(FULL))
                way(data)
                bad = []
                FLOW.check_object('flow', data, '', bad)        # the file breaks a rule, and no row of the table
                if rule not in ('R02', 'R05', 'R13'):
                    self.assertEqual(bad, [], (rule, number))
                self.define(data)
                with self.subTest(case=rule + ' way ' + str(number)):
                    for words in (['--dry-run'], [], ['--workspace', 'cedar-shop']):
                        code, text = self.call('run', 'full', *words)
                        self.assertEqual(code, 2, text)
                    self.assertEqual(self.runs(), [])
                    self.assertFalse(list(self.home.rglob('changed')))
                cases += 1
        self.assertEqual(cases, sum(len(ways) for ways in BREAKS.values()))
        self.COUNTS['rules R01 to R13, D01, D02: files that break one rule'] = cases
        # D01 is for the place of the run: the seat ghost is a seat of oak-studio, and of no other place.
        data = json.loads(json.dumps(FULL))
        data['members']['worker']['seat'] = 'ghost'
        data['graph']['change']['gate'] = 'production'
        self.define(data)
        self.assertEqual(self.call('run', 'full', '--workspace', 'oak-studio', '--dry-run')[0], 0)
        code, text = self.call('status', '--json')
        row = [row for row in json.loads(text)['flows'] if row['flow'] == 'full'][0]
        self.assertEqual((row['valid'], row['runs_in'], sorted(row['refused'])), (True, ['oak-studio'], ['cedar-shop', 'shared']))
        self.assertIn('the seat ghost has no seat file', row['refused']['shared'])

    # ------------------------------------------------------------ the schema: the run file, the events, the record of a yes

    def resting(self):
        """A run at rest: a result waits to be accepted, and a code step is behind it. Returns (folder, the files of the run now)."""
        (self.home / 'tools/third.py').write_text("import os, pathlib\npathlib.Path(os.environ['FOXRUN_RUN_DIR'], 'third-ran').write_text('x')\n")
        self.write_flow('resting', RESTING)
        self.assertEqual(self.call('run', 'resting')[0], 0)
        (folder,) = [self.home / 'runs' / name for name in self.runs()]
        (folder / 'review.md').write_text('verdict: fail\n')
        self.assertEqual(self.call('run', '--resume', folder.name)[0], 0)           # accepted, repeat-start, repeat
        (folder / 'review.md').write_text('verdict: pass\n')
        self.assertEqual(self.call('run', '--resume', folder.name)[0], 0)           # accepted; first waits for its yes
        self.assertEqual(self.call('run', '--resume', folder.name, '--yes', 'first', '--words', 'Yes. Go.')[0], 0)   # approval, code-start, code-step
        (folder / 'second.md').write_text('The second result.\n')
        names = [json.loads(line)['event'] for line in (folder / 'runner/events.jsonl').read_text().splitlines()]
        self.assertEqual(names, ['run-start', 'accepted', 'repeat-start', 'repeat', 'accepted', 'approval', 'code-start', 'code-step'])
        return folder

    def stays_closed(self, folder, label, codes=(2,)):
        """A resume, a dry run of it, and both forms of status: nothing is accepted, nothing runs, and no file of the run changes."""
        before = self.bytes_of(folder)
        with self.subTest(case=str(label)[:150]):
            code, text = self.call('run', '--resume', folder.name)
            self.assertIn(code, codes, text)
            self.assertEqual(before, self.bytes_of(folder), text)
            self.assertFalse((folder / 'third-ran').exists())
            for words in (['run', '--resume', folder.name, '--dry-run'], ['status', folder.name], ['status', folder.name, '--json'],
                          ['run', '--resume', folder.name, '--yes', 'first', '--words', 'Yes.'],
                          ['run', '--resume', folder.name, '--no', 'first', '--words', 'No.']):
                code, text = self.call(*words)
                # status <run> and a dry run of a blocked run end with 0 and say: blocked. Every other call ends with 1 or 2.
                self.assertTrue(code in (1, 2) or (code == 0 and ('State: blocked' in text or '"state": "blocked"' in text)), text)
                self.assertNotIn('NEXT  ', text)
                self.assertEqual(before, self.bytes_of(folder), text)
            code, text = self.call('status')
            self.assertEqual(code, 1, text)
            self.assertIn(folder.name + ': ', text)
            self.assertNotIn(folder.name + ': running', text)

    def test_schema_each_key_of_the_run_file_refuses_each_wrong_type_a_missing_value_and_an_unknown_key(self):
        folder = self.resting()
        file, log = folder / 'runner/run.yaml', folder / 'runner/events.jsonl'
        good, lines = json.loads(file.read_text()), log.read_text().splitlines()
        cases = 0

        def put(raw, with_hash):
            """Write the changed run file. with_hash: write its own hash into the event run-start too, so only the schema can stop it."""
            file.write_text(json.dumps(raw, indent=2, sort_keys=True) + '\n')
            start = json.loads(lines[0])
            if with_hash:
                start['frozen_sha256'] = hashlib.sha256(json.dumps({key: raw.get(key) for key in (
                    'run', 'flow', 'definition', 'inputs', 'workspace', 'task', 'definition_path', 'definition_sha256', 'definition_source',
                    'overrides')}, sort_keys=True).encode('utf-8')).hexdigest()
            log.write_text('\n'.join([json.dumps(start, sort_keys=True)] + lines[1:]) + '\n')
        put(good, True)
        self.assertEqual(self.call('status', folder.name)[0], 0)            # the helper itself writes a run that is fine
        for kind, key, need, type_, _ in FLOW.SCHEMA:
            if kind != 'run':
                continue
            self.assertEqual(need, 'must')
            changes = [('wrong type', value) for value in BAD[type_]] + [('missing', REMOVE)]
            for word, value in changes:
                for with_hash in (False, True):
                    raw = json.loads(json.dumps(good))
                    if value is REMOVE:
                        del raw[key]
                    else:
                        raw[key] = value
                    put(raw, with_hash)
                    self.stays_closed(folder, ('run file', key, word, value, 'hash made to fit' if with_hash else 'hash left'), codes=(1, 2))
                    cases += 1
        for extra in ('extra', 'gate', 'Workspace'):
            raw = dict(json.loads(json.dumps(good)), **{extra: 'x'})
            put(raw, True)
            self.stays_closed(folder, ('run file', 'unknown key', extra))
            cases += 1
        twice = json.dumps(good, sort_keys=True)[:-1] + ', "workspace": "cedar-shop", "definition": {"version": 1}}'
        for label, text in (('no JSON', '{'), ('a list', '[]'), ('empty', ''), ('a word', '"run"'), ('a key two times', twice)):
            file.write_text(text)
            self.stays_closed(folder, ('run file', label))
            cases += 1
        # the definition inside the run file is checked by the same validator as a file in a place
        for kind, key, need, type_, _ in FLOW.SCHEMA:
            for spot in ([['graph', 'review']] if kind == 'step' else [['members', 'worker']] if kind == 'member' else [[]] if kind == 'flow' else []):
                raw = json.loads(json.dumps(good))
                here = raw['definition']
                for name in spot:
                    here = here[name]
                here[key] = BAD[type_][1]
                put(raw, True)
                self.stays_closed(folder, ('run file', 'definition', kind, key, BAD[type_][1]))
                cases += 1
        put(good, True)
        self.assertGreater(cases, 250)
        self.COUNTS['run file keys: wrong type, missing, unknown key'] = cases
        code, text = self.call('run', '--resume', folder.name)             # the run file is put back: the run goes on, and code runs
        self.assertEqual(code, 0, text)
        self.assertTrue((folder / 'third-ran').exists())

    def test_schema_each_key_of_each_event_refuses_each_wrong_type_a_missing_value_and_an_unknown_key(self):
        folder = self.resting()
        log = folder / 'runner/events.jsonl'
        lines = log.read_text().splitlines()
        cases, seen = 0, set()
        for index, line in enumerate(lines):
            row = json.loads(line)
            rows = [r for r in FLOW.SCHEMA if r[0] in ('event', row['event'])]
            self.assertEqual({r[1] for r in rows}, set(row), row['event'])       # the runner wrote each key of the table, and no other
            seen.add(row['event'])
            changes = [(key, word, value) for _, key, _, type_, _ in rows
                       for word, value in [('wrong type', value) for value in BAD[type_]] + [('missing', REMOVE)]]
            changes += [('extra', 'unknown key', 'x'), ('gate', 'unknown key', 'passed'), ('event', 'unknown event', 'made-up'),
                        ('step', 'a step that is not in the run', 'ghost'), ('event', 'another event', 'run-done' if row['event'] != 'run-done' else 'repeat')]
            for key, word, value in changes:
                if key == 'step' and word == 'wrong type' and value is None and row['event'] in ('run-start', 'run-done'):
                    continue            # null is the right value there
                changed = dict(row)
                if value is REMOVE:
                    del changed[key]
                else:
                    changed[key] = value
                log.write_text('\n'.join(lines[:index] + [json.dumps(changed, sort_keys=True)] + lines[index + 1:]) + '\n')
                self.stays_closed(folder, ('event', index + 1, row['event'], key, word, value))
                cases += 1
            for label, text in (('no JSON', '{"event": '), ('a list', '[]'), ('an empty line', ''), ('a word', '"accepted"'), ('half a line', line[:len(line) // 2]),
                                ('a key two times', line[:-1] + ', "event": "run-done", "step": null}')):
                log.write_text('\n'.join(lines[:index] + [text] + lines[index + 1:]) + '\n')
                self.stays_closed(folder, ('event', index + 1, label))
                cases += 1
        for label, text in (('the file is empty', ''), ('the first event is gone', '\n'.join(lines[1:]) + '\n'),
                            ('the start is there two times', '\n'.join(lines[:1] + lines) + '\n'),
                            ('the start is not the first line', '\n'.join(lines[1:2] + lines[:1] + lines[2:]) + '\n')):
            log.write_text(text)
            self.stays_closed(folder, ('events', label), codes=(1, 2))
            cases += 1
        log.unlink()
        self.stays_closed(folder, ('events', 'the file is gone'))
        log.write_text('\n'.join(lines) + '\n')
        self.assertEqual(seen, set(FLOW.EVENTS) - {'run-refused', 'run-done'})
        self.assertGreater(cases, 400)
        code, text = self.call('run', '--resume', folder.name)             # the events are put back: the run goes on to its end
        self.assertEqual(code, 0, text)
        self.assertTrue((folder / 'third-ran').exists())
        # the two events of an end: a run that is done, and a run that is refused
        ended = {'run-done': folder}
        self.write_flow('code-gate', CODE_GATE)
        self.assertEqual(self.call('run', 'code-gate')[0], 0)
        ended['run-refused'] = [self.home / 'runs' / name for name in self.runs() if name.endswith('code-gate')][0]
        self.assertEqual(self.call('run', '--resume', ended['run-refused'].name, '--no', 'publish', '--words', 'No. Stop.')[0], 1)
        for event, run in ended.items():
            log = run / 'runner/events.jsonl'
            lines = log.read_text().splitlines()
            row = json.loads(lines[-1])
            self.assertEqual(row['event'], event)
            rows = [r for r in FLOW.SCHEMA if r[0] in ('event', event)]
            self.assertEqual({r[1] for r in rows}, set(row), event)
            for _, key, _, type_, _ in rows:
                for value in BAD[type_] + [REMOVE]:
                    if key == 'step' and value is None and event == 'run-done':
                        continue
                    changed = dict(row)
                    if value is REMOVE:
                        del changed[key]
                    else:
                        changed[key] = value
                    log.write_text('\n'.join(lines[:-1] + [json.dumps(changed, sort_keys=True)]) + '\n')
                    before = self.bytes_of(run)
                    with self.subTest(case=str((event, key, value))[:150]):
                        for words in (['run', '--resume', run.name], ['status', run.name], ['run', '--resume', run.name, '--dry-run']):
                            code, text = self.call(*words)
                            self.assertEqual(code, 2, text)
                            self.assertEqual(before, self.bytes_of(run))
                    cases += 1
            log.write_text('\n'.join(lines) + '\n')
            self.assertIn('Nothing was changed', self.call('run', '--resume', run.name)[1])
        self.COUNTS['event keys: wrong type, missing, unknown key, unknown event, broken line'] = cases

    def test_schema_each_key_of_the_record_of_a_yes_refuses_each_wrong_value_and_the_gate_stays_shut(self):
        (self.home / 'tools/third.py').write_text("import os, pathlib\npathlib.Path(os.environ['FOXRUN_RUN_DIR'], 'third-ran').write_text('x')\n")
        self.write_flow('asking', ASKING)
        self.assertEqual(self.call('run', 'asking')[0], 0)
        (folder,) = [self.home / 'runs' / name for name in self.runs()]
        (folder / 'ask.md').write_text('One ask.\n')
        self.assertEqual(self.call('run', '--resume', folder.name, '--yes', 'ask', '--words', 'Yes. Send it.')[0], 0)
        (folder / 'write.md').write_text('The page.\n')
        record = folder / 'runner/decisions/ask.yes.md'
        good = record.read_text()
        fields = dict(line.split(': ', 1) for line in good.splitlines())
        self.assertEqual(list(fields), [row[1] for row in FLOW.SCHEMA if row[0] == 'decision'])    # the runner wrote each key, in the order of the table
        other = hashlib.sha256(b'another result').hexdigest()
        texts = {'for': ['x', 'abc', other, FLOW.NOTHING, 'A' * 64], 'decision': ['no', 'maybe', 'YES', 'Yes'], 'by': [''], 'at': ['now', 'x', ''],
                 'words': ['', 'No. Do not send it.', "Don't.", 'wait']}
        cases = 0
        for key in fields:
            changes = [dict(fields, **{key: value}) for value in texts[key]] + [{k: v for k, v in fields.items() if k != key}]
            for changed in changes:
                for text in ('\n'.join(k + ': ' + v for k, v in changed.items()) + '\n',):
                    record.write_text(text)
                    self.gate_shut(folder, (key, changed.get(key, 'missing')))
                    cases += 1
        for label, text in (('a key two times', good + 'words: Yes.\n'), ('an unknown key', good + 'note: fine\n'), ('a free line', good + 'Go ahead.\n'),
                            ('free text', 'yes'), ('an empty file', ''), ('JSON', json.dumps(fields)), ('capital keys', good.replace('decision:', 'Decision:'))):
            record.write_text(text)
            self.gate_shut(folder, label)
            cases += 1
        record.unlink()
        self.gate_shut(folder, 'the record is gone')
        record.symlink_to(folder / 'ask.md')
        self.gate_shut(folder, 'the record is a link')
        record.unlink()
        record.write_text(good)
        self.assertGreater(cases, 20)
        self.COUNTS['record of a yes: wrong value, missing key, unknown key'] = cases + 2
        code, text = self.call('run', '--resume', folder.name)             # the record is put back: the run goes on to its end
        self.assertEqual(code, 0, text)
        self.assertTrue((folder / 'third-ran').exists())

    def gate_shut(self, folder, label):
        """The gate of ask is not passed: the step after it is not accepted, the code step does not run, and no event is written."""
        events = (folder / 'runner/events.jsonl').read_bytes()
        with self.subTest(case=str(label)[:150]):
            code, text = self.call('run', '--resume', folder.name)
            self.assertIn(code, (0, 1), text)
            self.assertIn('ask    waits-for-yes', text)
            self.assertNotIn('NEXT  ', text)
            self.assertEqual(events, (folder / 'runner/events.jsonl').read_bytes())
            self.assertFalse((folder / 'third-ran').exists())

    def test_schema_a_no_file_of_any_shape_ends_the_run(self):
        for number, make in enumerate((lambda f: f.write_text(''), lambda f: f.write_text('no'), lambda f: f.write_text('decision: yes\n'),
                                       lambda f: f.symlink_to(f.parent / 'nowhere'), lambda f: f.mkdir())):
            self.write_flow('code-gate', CODE_GATE)
            self.assertEqual(self.call('run', 'code-gate')[0], 0)
            folder = self.home / 'runs' / self.runs()[-1]
            (folder / 'runner/decisions').mkdir(exist_ok=True)
            make(folder / 'runner/decisions/publish.no.md')
            with self.subTest(case=number):
                code, text = self.call('run', '--resume', folder.name, '--yes', 'publish', '--words', 'Yes. Publish it.')
                self.assertEqual(code, 2, text)
                code, text = self.call('run', '--resume', folder.name)
                self.assertEqual(code, 1, text)
                self.assertIn('State: refused', text)
                self.assertFalse((folder / 'changed').exists())

    # ------------------------------------------------------------ fail closed: each place of the lookup order

    def break_place(self, folder, how):
        """Make one place folder unusable in one way. The folder is put back when the test ends."""
        outside = Path(self.temp.name).resolve() / ('outside-' + how.replace(' ', '-'))
        if how == 'nobody may read it':
            folder.chmod(0)
            self.addCleanup(folder.chmod, 0o755)
            return
        shutil.rmtree(str(folder))
        if how == 'a file in its place':
            folder.write_text('not a folder\n')
        elif how == 'a link that leads nowhere':
            folder.symlink_to(folder.parent / 'not-there', target_is_directory=True)
        elif how == 'a link to itself':
            folder.symlink_to(folder, target_is_directory=True)
        elif how == 'a link out of the two homes':
            # the folder outside holds a definition of the name; it is never read
            (outside / 'publish').mkdir(parents=True)
            (outside / 'publish/flow.yaml').write_text(json.dumps(PUBLISH))
            (outside / 'publish.yaml').write_text(json.dumps(PUBLISH))
            folder.symlink_to(outside, target_is_directory=True)
        elif how != 'it is missing':
            raise AssertionError(how)

    WAYS = ('nobody may read it', 'a file in its place', 'a link that leads nowhere', 'a link to itself', 'a link out of the two homes')

    def test_closed_the_test_knows_every_place_of_the_lookup_order(self):
        environment = mock.patch.dict(os.environ, FOXRUN_HOME=str(self.home),
                                           FOXRUN_PORTFOLIO=str(self.portfolio))
        environment.start()
        self.addCleanup(environment.stop)
        places = FLOW.flow_places(['cedar-shop'])
        self.assertEqual([place[1] for place in places], list(PLACES))
        self.assertEqual([str(place[2]) for place in places], [str(Path(self.temp.name).resolve() / path) for path in PLACES.values()])

    def test_closed_each_place_that_can_not_be_read_stops_the_name_and_nothing_runs(self):
        cases = 0
        for place, path in PLACES.items():
            for how in self.WAYS:
                with self.subTest(place=place, how=how):
                    self.one_broken_place(place, path, how)
                self.doCleanups()
                self.setUp()
                cases += 1
        self.assertEqual(cases, len(PLACES) * len(self.WAYS))
        self.COUNTS['places of the lookup order: each one broken in each way'] = cases

    def one_broken_place(self, place, path, how):
        root = Path(self.temp.name).resolve()
        folder = root / path
        # The name is defined, with code and no gate, in a shared place that stays whole. The workspace has its own, with a gate.
        whole = 'system/skills' if place == 'skill source' else 'system/skillwright/skills'
        (root / whole / 'publish').mkdir(parents=True)
        (root / whole / 'publish/flow.yaml').write_text(json.dumps(PUBLISH))
        if not place.startswith('workspace ') or how == 'nobody may read it':
            gated = json.loads(json.dumps(PUBLISH))
            gated['graph']['change']['gate'] = 'production'
            (self.portfolio / 'cedar-shop/skills/publish').mkdir(parents=True)
            (self.portfolio / 'cedar-shop/skills/publish/flow.yaml').write_text(json.dumps(gated))
            code, text = self.call('run', 'publish', '--workspace', 'cedar-shop', '--dry-run')
            self.assertEqual((code, 'production gate' in text), (0, True), text)       # before the break: the local gate is in the run
        self.break_place(folder, how)
        shared_place = not place.startswith('workspace ')
        for words in (['--workspace', 'cedar-shop'], ['--workspace', 'cedar-shop', '--dry-run'],
                      [], ['--dry-run']):
            code, text = self.call('run', 'publish', *words)
            if '--workspace' in words or shared_place:
                self.assertEqual(code, 2, text)
                self.assertIn('flow publish can not be looked up', text)
                self.assertIn(str(folder) + ': ', text)
            else:
                # A shared run reads the shared places only. The place of a workspace it was not given is not one of its places.
                self.assertEqual(code, 0, text)
                self.assertIn('Workspace: none (a shared run)', text)
        # by its path, the shared file is refused in the same way for the run that reads the broken place
        code, text = self.call('run', str(root / whole / 'publish/flow.yaml'), '--workspace', 'cedar-shop')
        self.assertEqual(code, 2, text)
        self.assertIn(str(folder) + ': ', text)
        made = self.runs()
        self.assertEqual(len(made), 0 if shared_place else 1, made)     # the one run is the shared run above, and it is a shared run
        if made:
            info = json.loads((self.home / 'runs' / made[0] / 'runner/run.yaml').read_text())
            self.assertEqual((info['workspace'], info['definition_path']), (None, str(root / whole / 'publish/flow.yaml')))
        code, text = self.call('status')
        self.assertEqual(code, 1, text)
        blocked_paths = [str(folder)]
        if place == 'system workflow' and how in ('nobody may read it', 'a file in its place', 'a link to itself'):
            blocked_paths.append(str(folder / '.product'))
        self.assertIn('Places that can not be read: ' + str(len(blocked_paths)), text)
        self.assertIn(str(folder) + ': ', text)
        code, text = self.call('status', '--json')
        self.assertEqual(code, 1, text)
        data = json.loads(text)
        self.assertEqual([p['folder'] for p in data['places'] if p['error']], blocked_paths)
        row = [row for row in data['flows'] if row['flow'] == 'publish' and row['level'] == 'shared'][0]
        self.assertEqual(row['runs_in'], [] if shared_place else ['shared'])
        self.assertNotIn('cedar-shop', row['runs_in'])
        self.assertIn(str(folder), ' '.join(row['refused'].values()))

    SLOTS = ('the skill folder: nobody may read it', 'the skill folder: a link that leads nowhere', 'the skill folder: a link to itself',
             'the skill folder: a link out of the two homes', 'the file: nobody may read it', 'the file: a link that leads nowhere',
             'the file: a link to itself', 'the file: a link out of the two homes', 'the file: a folder', 'the file: no YAML',
             'the file: no text', 'the file: empty', 'the file: a wrong key', 'the file: another flow name')

    def test_closed_each_definition_of_the_name_that_can_not_be_proven_stops_the_name_and_nothing_runs(self):
        cases = 0
        for place, path in PLACES.items():
            for how in self.SLOTS + ('the file: the name ends with .yml',):
                if how.startswith('the skill folder') and place.endswith('workflow'):
                    continue            # a workflow is one file; it has no skill folder
                if how.endswith('.yml') and not place.endswith('workflow'):
                    continue
                with self.subTest(place=place, how=how):
                    self.one_broken_definition(place, path, how)
                self.doCleanups()
                self.setUp()
                cases += 1
        self.assertGreater(cases, 50)
        self.COUNTS['definitions of the name: each place, each way it can not be proven'] = cases

    def one_broken_definition(self, place, path, how):
        root = Path(self.temp.name).resolve()
        outside = root / 'outside'
        (outside / 'publish').mkdir(parents=True)
        (outside / 'publish/flow.yaml').write_text(json.dumps(PUBLISH))
        whole = 'system/skills' if place == 'skill source' else 'system/skillwright/skills'
        (root / whole / 'publish').mkdir(parents=True)
        (root / whole / 'publish/flow.yaml').write_text(json.dumps(PUBLISH))
        is_file_place = place.endswith('workflow')
        holder = root / path / 'publish'
        file = root / path / 'publish.yaml' if is_file_place else holder / 'flow.yaml'
        what, _, way = how.partition(': ')
        if what == 'the skill folder':
            if way == 'nobody may read it':
                holder.mkdir()
                (holder / 'flow.yaml').write_text(json.dumps(PUBLISH))
                holder.chmod(0)
                self.addCleanup(holder.chmod, 0o755)
            else:
                holder.symlink_to({'a link that leads nowhere': root / 'not-there', 'a link to itself': holder,
                                   'a link out of the two homes': outside / 'publish'}[way], target_is_directory=True)
        else:
            if not is_file_place:
                holder.mkdir()
            if way == 'nobody may read it':
                file.write_text(json.dumps(PUBLISH))
                file.chmod(0)
                self.addCleanup(file.chmod, 0o644)
            elif way.startswith('a link'):
                file.symlink_to({'a link that leads nowhere': root / 'not-there.yaml', 'a link to itself': file,
                                 'a link out of the two homes': outside / 'publish/flow.yaml'}[way])
            elif way == 'a folder':
                file.mkdir()
            elif way == 'the name ends with .yml':
                file = file.with_suffix('.yml')
                file.write_text(json.dumps(PUBLISH))
            else:
                file.write_bytes({'no YAML': b'{{{{ this is : not [ a file\n', 'no text': b'\xff\xfe\x00\x80', 'empty': b'',
                                  'a wrong key': json.dumps(dict(PUBLISH, extra=1)).encode(),
                                  'another flow name': json.dumps(dict(PUBLISH, flow='other')).encode()}[way])
        shared_place = not place.startswith('workspace ')
        name = 'publish.yml' if way == 'the name ends with .yml' else 'publish'
        for words in (['--workspace', 'cedar-shop'], ['--workspace', 'cedar-shop', '--dry-run'], [], ['--dry-run']):
            code, text = self.call('run', 'publish', *words)
            if way == 'the name ends with .yml':
                self.assertEqual(code, 0 if '--dry-run' in words else 0, text)      # publish.yml is not the name publish; status names it
            elif '--workspace' in words or shared_place:
                self.assertEqual(code, 2, text)
                self.assertIn(str(file if what == 'the file' else holder / 'flow.yaml'), text)
            else:
                self.assertEqual(code, 0, text)
                self.assertIn('Workspace: none (a shared run)', text)
        if way != 'the name ends with .yml':
            for made in self.runs():
                self.assertIsNone(json.loads((self.home / 'runs' / made / 'runner/run.yaml').read_text())['workspace'])
            self.assertEqual(len(self.runs()), 0 if shared_place else 1)
        code, text = self.call('status', '--json')
        self.assertEqual(code, 1, text)
        rows = [row for row in json.loads(text)['flows'] if row['flow'] == name and not row['valid']]
        self.assertEqual(len(rows), 1, text[:600])
        self.assertTrue(rows[0]['problems'])
        self.assertFalse(rows[0]['taken'])
        self.assertIn('NOT VALID', self.call('status')[1])

    # ------------------------------------------------------------ the two probes of the seventh reader, as the reader asked for them

    def test_reader7_a_local_skills_folder_nobody_may_read_never_gives_the_shared_code_without_the_local_gate(self):
        # o2-python-r7b/review1/gate-place-probe.py. On r7 the shared code ran to done with no approval event.
        self.write_flow('publish', json.dumps(PUBLISH), skill=True)
        gated = json.loads(json.dumps(PUBLISH))
        gated['graph']['change']['gate'] = 'production'
        place = self.portfolio / 'cedar-shop/skills'
        (place / 'publish').mkdir()
        (place / 'publish/flow.yaml').write_text(json.dumps(gated))
        self.assertIn('production gate', self.flow('run', 'publish', '--workspace', 'cedar-shop', '--dry-run'))
        place.chmod(0)
        self.addCleanup(place.chmod, 0o755)
        output = self.flow('run', 'publish', '--workspace', 'cedar-shop', expected=2)
        self.assertIn('flow publish can not be looked up', output)
        self.assertIn(str(place) + ': the folder can not be listed', output)
        self.assertIn(str(place), self.flow('run', 'publish', '--workspace', 'cedar-shop', '--dry-run', expected=2))
        self.assertEqual(list((self.home / 'runs').iterdir()), [])
        self.assertFalse(list(self.home.rglob('changed')))
        listing = self.flow('status', expected=1)
        self.assertIn('Places that can not be read: 1', listing)
        self.assertIn('workspace skill of cedar-shop: ' + str(place) + ': the folder can not be listed', listing)
        data = json.loads(self.flow('status', '--json', expected=1))
        self.assertEqual([(p['workspace'], p['folder'], bool(p['error'])) for p in data['places'] if p['error']], [('cedar-shop', str(place), True)])
        self.assertEqual([row['runs_in'] for row in data['flows'] if row['flow'] == 'publish'], [['shared']])

    def test_reader7_a_seat_list_a_numeric_skill_and_a_command_with_no_script_start_nothing_and_run_no_code(self):
        # o2-python-r7b/review1/new-probes.py. On r7 each one got a run folder and a Traceback; one ran code first.
        base = {'version': 1, 'flow': 'probe', 'purpose': 'Check a malformed definition.', 'members': {'worker': {'seat': 'mercer'}},
                'graph': {'prepare': {'member': 'worker', 'done_when': {'file': 'prepare.md'}}, 'change': {'run': CHANGE}}}
        cases = {'a seat that is a list': lambda d: d['members']['worker'].update(seat=['mercer']),
                 'a skill that is a number': lambda d: d['graph']['prepare'].update(skill=1),
                 'a command with no script': lambda d: d['graph']['change'].update(run=['python3']),
                 'a step name that is a number': lambda d: d['graph'].update({'1': d['graph'].pop('prepare')}),
                 'a loop with an unknown key': lambda d: d.update(loop={'repiar': {'on': 'prepare', 'repeat': ['prepare'], 'max_rounds': 2}}),
                 'a verdict that is the text false': lambda d: d['graph']['prepare'].update(verdict='false')}
        for label, change_it in cases.items():
            data = json.loads(json.dumps(base))
            change_it(data)
            self.write_flow('probe', json.dumps(data))
            with self.subTest(case=label):
                row = [row for row in json.loads(self.flow('status', '--json', expected=1))['flows'] if row['flow'] == 'probe'][0]
                self.assertEqual((row['valid'], row['taken']), (False, False))
                for words in (['--dry-run'], []):
                    output = self.flow('run', 'probe', *words, expected=2)
                    self.assertIn('is not valid', output)
                    self.assertNotIn('Traceback', output)
                self.assertEqual(list((self.home / 'runs').iterdir()), [])
                self.assertFalse(list(self.home.rglob('changed')))

    # ------------------------------------------------------------ fail closed: the rest

    def test_closed_the_workspaces_are_the_list_of_the_person_file_when_it_has_one(self):
        (self.portfolio / 'oak-studio/skills').mkdir(parents=True)
        (self.portfolio / 'loose-folder').mkdir()
        (self.home / 'config/person.json').write_text(json.dumps({'name': 'avery', 'workspaces': ['cedar-shop', 'pine-yard']}))
        code, text = self.call('run', 'operate-amazon', '--workspace', 'oak-studio', '--input', 'listing=x', '--dry-run')
        self.assertEqual(code, 2, text)
        self.assertIn('unknown workspace: oak-studio. The workspaces are: cedar-shop, pine-yard', text)
        self.assertEqual(self.call('run', 'operate-amazon', '--workspace', 'cedar-shop', '--input', 'listing=x', '--dry-run')[0], 0)
        code, text = self.call('run', 'operate-amazon', '--workspace', 'pine-yard', '--input', 'listing=x', '--dry-run')
        self.assertEqual(code, 0, text)                                     # the list names it; its skills folder is missing: read as empty
        code, text = self.call('status', '--json')
        data = json.loads(text)
        self.assertEqual((code, data['workspaces']), (0, ['cedar-shop', 'pine-yard']))
        self.assertIn(str(self.portfolio / 'pine-yard/skills'), [p['folder'] for p in data['places'] if p['missing']])
        (self.home / 'config/person.json').write_text(json.dumps({'name': 'avery', 'workspaces': 'cedar-shop'}))
        for words in (['status'], ['run', 'operate-amazon', '--input', 'listing=x', '--dry-run']):
            self.assertEqual(self.call(*words)[0], 2)                       # a list that is not a list stops every word

    def test_closed_a_portfolio_that_can_not_be_listed_stops_every_run_in_a_workspace(self):
        self.portfolio.chmod(0)
        self.addCleanup(self.portfolio.chmod, 0o755)
        code, text = self.call('run', 'operate-amazon', '--workspace', 'cedar-shop', '--input', 'listing=x', '--dry-run')
        self.assertEqual(code, 2, text)
        code, text = self.call('status')
        self.assertEqual(code, 1, text)
        self.assertIn('the workspaces: ' + str(self.portfolio), text)

    def test_closed_a_seat_file_that_goes_away_after_the_start_blocks_the_run(self):
        self.write_flow('resting', RESTING)
        (self.home / 'tools/third.py').write_text('raise SystemExit(0)\n')
        self.assertEqual(self.call('run', 'resting')[0], 0)
        folder = self.home / 'runs' / self.runs()[0]
        (folder / 'review.md').write_text('verdict: pass\n')
        (self.home / 'agents/mercer.md').unlink()
        before = self.bytes_of(folder)
        code, text = self.call('run', '--resume', folder.name)
        self.assertEqual(code, 1, text)
        self.assertIn('State: blocked', text)
        self.assertIn('the definition is not valid now: member worker: the seat mercer has no seat file', text)
        self.assertNotIn('NEXT  ', text)
        self.assertEqual(before, self.bytes_of(folder))
        (self.home / 'agents/mercer.md').write_text('# Mercer\n')
        self.assertEqual(self.call('run', '--resume', folder.name)[0], 0)
        self.assertIn('accepted', (folder / 'runner/events.jsonl').read_text())

    def test_closed_a_run_whose_workspace_is_not_a_workspace_now_is_blocked(self):
        self.assertEqual(self.call('run', 'operate-amazon', '--workspace', 'cedar-shop', '--input', 'listing=x')[0], 0)
        folder = self.home / 'runs' / self.runs()[0]
        (folder / 'audit.md').write_text('findings\n')
        (self.home / 'config/person.json').write_text(json.dumps({'name': 'avery', 'workspaces': ['oak-studio']}))
        before = self.bytes_of(folder)
        code, text = self.call('run', '--resume', folder.name)
        self.assertEqual(code, 1, text)
        self.assertIn('the workspace of this run is not a workspace now: cedar-shop', text)
        self.assertEqual(before, self.bytes_of(folder))

    def test_closed_a_path_inside_a_place_that_can_not_be_read_is_refused_with_the_place(self):
        place = self.portfolio / 'cedar-shop/skills'
        (place / 'publish').mkdir()
        (place / 'publish/flow.yaml').write_text(json.dumps(PUBLISH))
        place.chmod(0)
        self.addCleanup(place.chmod, 0o755)
        for words in ([], ['--workspace', 'cedar-shop']):
            code, text = self.call('run', str(place / 'publish/flow.yaml'), *words)
            self.assertEqual(code, 2, text)
            self.assertIn(str(place), text)
        self.assertEqual(self.runs(), [])

    def test_closed_a_local_folder_with_the_name_in_other_letters_never_gives_the_shared_code(self):
        self.write_flow('publish', json.dumps(PUBLISH), skill=True)
        gated = json.loads(json.dumps(PUBLISH))
        gated['graph']['change']['gate'] = 'production'
        for folder, flow in (('Publish', 'publish'), ('PUBLISH', 'PUBLISH')):
            place = self.portfolio / 'cedar-shop/skills' / folder
            place.mkdir()
            (place / 'flow.yaml').write_text(json.dumps(dict(gated, flow=flow)))
            with self.subTest(case=folder):
                for words in ([], ['--dry-run']):
                    code, text = self.call('run', 'publish', '--workspace', 'cedar-shop', *words)
                    self.assertEqual(code, 2, text)
                    self.assertIn(str(place / 'flow.yaml'), text)
                    self.assertIn('is not taken from another place in its stead', text)
                self.assertEqual(self.runs(), [])
                self.assertEqual(self.call('status')[0], 1)
            shutil.rmtree(str(place))
        self.assertEqual(self.call('run', 'publish', '--workspace', 'cedar-shop', '--dry-run')[0], 0)

    def test_closed_a_workspace_that_is_a_link_out_of_the_two_homes_is_a_place_that_can_not_be_read(self):
        outside = Path(self.temp.name).resolve() / 'outside/pine-yard'
        (outside / 'skills/publish').mkdir(parents=True)
        (outside / 'skills/publish/flow.yaml').write_text(json.dumps(PUBLISH))
        (self.portfolio / 'pine-yard').symlink_to(outside, target_is_directory=True)
        code, text = self.call('run', 'publish', '--workspace', 'pine-yard')
        self.assertEqual(code, 2, text)
        self.assertIn(str(self.portfolio / 'pine-yard/skills') + ': the folder is a link that leaves the two homes', text)
        self.assertEqual(self.runs(), [])
        code, text = self.call('status')
        self.assertEqual(code, 1, text)
        self.assertIn('Places that can not be read: 1', text)

    def test_closed_an_event_of_a_code_step_for_another_command_runs_nothing(self):
        self.write_flow('code-gate', CODE_GATE)
        self.assertEqual(self.call('run', 'code-gate')[0], 0)
        folder = self.home / 'runs' / self.runs()[0]
        log = folder / 'runner/events.jsonl'
        for event, more in (('code-step', {'exit': 0, 'detail': ''}), ('code-start', {'pid': 1})):
            lines = log.read_text()
            row = dict({'at': NOW, 'ts': time.time(), 'event': event, 'step': 'publish', 'attempt': 1, 'command_sha256': 'a' * 64}, **more)
            log.write_text(lines + json.dumps(row) + '\n')
            with self.subTest(case=event):
                code, text = self.call('run', '--resume', folder.name)
                self.assertEqual(code, 1, text)
                self.assertIn('an event of this code step is for another command', text)
                code, text = self.call('run', '--resume', folder.name, '--yes', 'publish', '--words', 'Yes. Publish it.')
                self.assertEqual(code, 2, text)
                self.assertFalse((folder / 'changed').exists())
            log.write_text(lines)

    def test_closed_an_end_event_that_the_events_do_not_carry_blocks_the_run(self):
        folder = self.resting()
        log = folder / 'runner/events.jsonl'
        lines = log.read_text()
        done = json.dumps({'at': NOW, 'ts': time.time(), 'event': 'run-done', 'step': None})
        refused = json.dumps({'at': NOW, 'ts': time.time(), 'event': 'run-refused', 'step': 'first', 'words': 'No.'})
        for label, text in (('run-done while steps wait', lines + done + '\n'), ('an end, then more events', lines + refused + '\n' + lines.splitlines()[-1] + '\n'),
                            ('two ends', lines + refused + '\n' + refused + '\n'), ('run-done in the middle', '\n'.join(lines.splitlines()[:3] + [done] + lines.splitlines()[3:]) + '\n')):
            log.write_text(text)
            self.stays_closed(folder, label, codes=(1,))
            code, text = self.call('run', '--resume', folder.name)
            self.assertIn('State: blocked', text)
            self.assertNotIn('Nothing was changed: this run is done', text)
        log.write_text(lines)
        self.assertEqual(self.call('run', '--resume', folder.name)[0], 0)
        self.assertTrue((folder / 'third-ran').exists())

    def test_closed_a_run_folder_and_a_decisions_folder_nobody_may_read_are_named_and_nothing_runs(self):
        folder = self.resting()
        (self.home / 'runs/not-a-run').mkdir()                              # a plain folder beside the runs is passed over
        self.assertEqual(self.call('status')[0], 0)
        for closed in (folder, folder / 'runner', folder / 'runner/decisions'):
            closed.chmod(0)
            try:
                with self.subTest(case=closed.name):
                    code, text = self.call('run', '--resume', folder.name)
                    self.assertIn(code, (2, 3), text)
                    code, text = self.call('status')
                    if closed.name != 'decisions':
                        self.assertEqual(code, 1, text)
                        self.assertIn(folder.name + ': NOT READABLE', text)
            finally:
                closed.chmod(0o755)
            self.assertFalse((folder / 'third-ran').exists())
        self.assertEqual(self.call('run', '--resume', folder.name)[0], 0)
        self.assertTrue((folder / 'third-ran').exists())

    def test_closed_an_input_given_two_times_and_a_runs_folder_that_can_not_be_read_are_refused(self):
        code, text = self.call('run', 'operate-amazon', '--input', 'listing=a', '--input', 'listing=b', '--dry-run')
        self.assertEqual(code, 2, text)
        shutil.rmtree(str(self.home / 'runs'))
        self.assertEqual(self.call('status')[0], 0)                         # no runs folder yet: no run yet
        (self.home / 'runs').write_text('a file\n')
        self.assertEqual(self.call('status')[0], 2)
        self.assertEqual(self.call('run', 'operate-amazon', '--input', 'listing=a')[0], 2)

    def test_closed_an_error_the_program_did_not_expect_stops_it_with_exit_code_4(self):
        def broken(args):
            raise KeyError('a key the program did not expect')
        saved, FLOW.status = FLOW.status, broken
        self.addCleanup(setattr, FLOW, 'status', saved)
        out = io.StringIO()
        with contextlib.redirect_stderr(out):
            code = FLOW.main(['status'])
        self.assertEqual(code, 4)
        self.assertIn('internal error, the program stops: KeyError', out.getvalue())


if __name__ == '__main__':
    unittest.main()
