#!/usr/bin/env python3
"""T742: a failed ship keeps each failing canary's full output beside its receipt,
and a canary that fails once is run once more before the ship fails."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import skill_ship  # noqa: E402
from skill_scoped import keep_failure_output  # noqa: E402


class FailureEvidence(unittest.TestCase):
    def tool(self, folder):
        return types.SimpleNamespace(SHIPS=Path(folder), write_json=skill_ship.write_json)

    def test_failed_canary_output_is_saved_and_its_path_printed(self):
        report = dict(required_skills=['close'], prompt='p', runtimes=dict(
            claude=dict(result='failed', stdout='partial reply\n', stderr='Error: hook said no\n', returncode=1),
            codex=dict(result='passed', stdout='close: present\n', stderr='')))
        error = skill_ship.ShipStepError('fresh canaries failed: claude', report)
        with tempfile.TemporaryDirectory() as folder:
            receipt = dict(release_id='R1')
            printed = io.StringIO()
            with contextlib.redirect_stderr(printed):
                evidence = keep_failure_output(self.tool(folder), receipt, error)
            self.assertEqual(evidence, Path(folder) / 'R1-evidence')
            self.assertEqual((evidence / 'claude.stderr.txt').read_text(), 'Error: hook said no\n')
            self.assertEqual((evidence / 'claude.stdout.txt').read_text(), 'partial reply\n')
            self.assertFalse((evidence / 'codex.stdout.txt').exists())
            self.assertEqual(json.loads((evidence / 'failure.json').read_text())['output'], report)
            self.assertEqual(receipt['failure_output'], report)
            self.assertEqual(receipt['evidence'], str(evidence))
            self.assertIn(str(evidence), printed.getvalue())

    def test_error_without_output_writes_nothing(self):
        with tempfile.TemporaryDirectory() as folder:
            receipt = dict(release_id='R2')
            self.assertIsNone(keep_failure_output(self.tool(folder), receipt, RuntimeError('plain')))
            self.assertEqual(receipt, dict(release_id='R2'))
            self.assertEqual(list(Path(folder).iterdir()), [])


class CanaryRetry(unittest.TestCase):
    def overrides(self, script):
        return {runtime: sys.executable + ' -B ' + str(script) for runtime in ('claude', 'codex', 'hermes')}

    def test_a_canary_that_fails_once_passes_and_keeps_the_first_attempt(self):
        with tempfile.TemporaryDirectory() as folder:
            script = Path(folder) / 'flaky.py'
            script.write_text('import sys\nfrom pathlib import Path\n'
                              'mark = Path(sys.argv[0]).with_name("ran-" + sys.argv[1])\n'
                              'if not mark.exists():\n    mark.write_text("1"); print("Error: login refresh"); sys.exit(1)\n'
                              'print("close: present")\n')
            overrides = {r: sys.executable + ' -B ' + str(script) + ' ' + r for r in ('claude', 'codex', 'hermes')}
            report = skill_ship.run_fresh_canaries(['close'], 'p', overrides)
            claude = report['runtimes']['claude']
            self.assertEqual(claude['result'], 'passed')
            self.assertEqual(claude['first_attempt']['result'], 'failed')
            self.assertIn('Error: login refresh', claude['first_attempt']['stdout'])

    def test_a_canary_that_fails_twice_still_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            script = Path(folder) / 'absent.py'
            script.write_text('print("close: absent")\n')
            with self.assertRaises(skill_ship.ShipStepError) as caught:
                skill_ship.run_fresh_canaries(['close'], 'p', self.overrides(script))
            claude = caught.exception.output['runtimes']['claude']
            self.assertEqual(claude['result'], 'failed')
            self.assertEqual(claude['first_attempt']['result'], 'failed')


class HiddenSkillCanary(unittest.TestCase):
    """T675: a skill with `disable-model-invocation: true` is listed by Claude, never shown to the model."""

    def run_canaries(self, folder, listed):
        stream = Path(folder) / 'claude.py'
        events = [dict(type='system', subtype='init', skills=listed),
                  dict(type='result', result='close: present\nto-tickets: absent')]
        stream.write_text('import json\nfor event in %r:\n    print(json.dumps(event))\n' % events)
        plain = Path(folder) / 'plain.py'
        plain.write_text('print("close: present")\nprint("to-tickets: present")\n')
        overrides = dict(claude=sys.executable + ' -B ' + str(stream),
                         codex=sys.executable + ' -B ' + str(plain), hermes=sys.executable + ' -B ' + str(plain))
        return skill_ship.run_fresh_canaries(['close', 'to-tickets'], 'p', overrides, ['to-tickets'])

    def test_hidden_skill_is_present_when_claude_lists_it(self):
        with tempfile.TemporaryDirectory() as folder:
            claude = self.run_canaries(folder, ['close', 'to-tickets'])['runtimes']['claude']
            self.assertEqual(claude['result'], 'passed')
            self.assertEqual(claude['statuses'], {'close': 'present', 'to-tickets': 'present'})
            self.assertEqual(claude['checked_by_list'], ['to-tickets'])
            self.assertEqual(claude['stdout'], 'close: present\nto-tickets: absent')

    def test_hidden_skill_missing_from_the_list_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(skill_ship.ShipStepError) as caught:
                self.run_canaries(folder, ['close'])
            claude = caught.exception.output['runtimes']['claude']
            self.assertEqual(claude['absent'], ['to-tickets'])

    def test_hidden_from_model_reads_the_front_matter(self):
        with tempfile.TemporaryDirectory() as folder:
            for name, extra in (('to-tickets', 'disable-model-invocation: true\n'), ('close', ''),
                                ('body-only', '')):
                (Path(folder) / name).mkdir()
                body = 'disable-model-invocation: true\n' if name == 'body-only' else ''
                (Path(folder) / name / 'SKILL.md').write_text(
                    '---\nname: %s\ndescription: d\n%s---\n%s' % (name, extra, body))
            self.assertEqual(skill_ship.hidden_from_model(Path(folder), ['close', 'to-tickets', 'body-only', 'gone']),
                             ['to-tickets'])

    def test_claude_canary_asks_for_the_stream(self):
        command = skill_ship.canary_command('claude', 'p', {})
        self.assertIn('stream-json', command)
        self.assertIn('--verbose', command)

    def test_hermes_canary_has_no_approval_bypass(self):
        command = skill_ship.canary_command('hermes', 'p', {})
        self.assertNotIn('--yolo', command)
        self.assertEqual(command[command.index('-t') + 1], 'skills')
        self.assertIn('--ignore-rules', command)


if __name__ == '__main__':
    unittest.main(verbosity=2)
