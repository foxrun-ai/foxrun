"""Round-four clearance cases. All files and lead statements are synthetic."""

from __future__ import annotations

import sys as _fox_sys
from pathlib import Path as _FoxPath
_fox_root = next(p for p in _FoxPath(__file__).resolve().parents if (p / 'base/core.py').is_file())
_fox_sys.path[:0] = [str(_fox_root / p) for p in ('base', 'work', 'events', 'decisions', 'memory', 'people', 'design', 'capture')]
_fox_sys.path.insert(0, str(_fox_root))
from base.tests.support import setup as _fox_test_setup
_fox_test_setup()
import json
from pathlib import Path
import sys
import tempfile
import unittest

import reader_check as rc

UNPROVEN = 'search found no reader; not proven by a dry test'


class Round4ClearanceTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.src = self.base/'src'; self.src.mkdir()
        self.target = self.base/'data/rules.yaml'
        self.target.parent.mkdir(); self.target.write_text('synthetic\n')
        self.plan = {'thing': {'kind': 'file', 'name': 'rules.yaml', 'path': str(self.target)},
                     'roots': [{'path': str(self.src), 'program': 'plant'}], 'work_lead': 'test lead'}
        self.index = 0

    def check(self, execute=False):
        self.index += 1
        return rc.check(self.plan, self.base/f'out-{self.index}', self.base/f'trial-{self.index}', execute)

    def reader(self, root=None):
        root = root or self.src
        (root/'probe.py').write_text('import sys\nassert len(sys.argv) == 2\n')
        return {'program': 'plant', 'workspace': str(root), 'offline': True,
                'commands': [[sys.executable, 'probe.py', '{copy}']]}

    def exemption(self, root=None, **changes):
        return {'path': str(root or self.src), 'by': 'test lead', 'at': '2026-10-06T21:00:00+00:00',
                'reason': 'synthetic fixture has no offline test adapter', **changes}

    def assert_unproven(self, execute=False):
        code, verdict = self.check(execute)
        self.assertNotEqual(code, 0)
        self.assertEqual(verdict['verdict'], UNPROVEN)
        self.assertFalse(verdict['blocking_readers'])
        self.assertIn('reader roots lack a dry test or named work lead exemption', verdict['reasons'])

    def test_built_reader_pr24_zero_commands(self):
        (self.src/'probe.py').write_text('import pathlib,sys\nbase=pathlib.Path(sys.argv[1]).parent\n(base / ("rules" + ".yaml")).read_text()\n')
        self.assert_unproven(True)

    def runtime_case(self, kind, name, body):
        self.plan['thing'] = {'kind': kind, 'name': name}
        (self.src/'r.py').write_text(body)
        self.assert_unproven()

    def test_file_joined_parts(self):
        self.runtime_case('file', 'rules.yaml', 'open(os.path.join(BASE, "rules" + ".yaml"))\n')

    def test_file_fstring_ext(self):
        self.runtime_case('file', 'rules.yaml', 'name = "rules"\nopen(f"{BASE}/{name}.yaml")\n')

    def test_file_pathlib_stem(self):
        self.runtime_case('file', 'rules.yaml', 'p = (BASE / "rules").with_suffix(".yaml")\n')

    def test_file_glob(self):
        self.runtime_case('file', 'rules.yaml', 'for p in BASE.glob("*.yaml"): load(p)\n')

    def test_folder_env(self):
        self.runtime_case('folder', '.small-talk', 'STATE = Path(os.environ["SMALL_TALK_STATE"])\n')

    def test_folder_parts(self):
        self.runtime_case('folder', '.small-talk', 'STATE = Path.home() / ("." + "small" + "-talk")\n')

    def test_program_parts(self):
        self.plan['thing'] = {'kind': 'program', 'name': 'small-talk'}
        (self.src/'r.js').write_text('const bin = ["small","talk"].join("-"); spawn(bin)\n')
        self.assert_unproven()

    def test_each_reader_root_requires_a_command(self):
        other = self.base/'other'; other.mkdir()
        self.plan['roots'].append({'path': str(other), 'program': 'plant'})
        self.plan['readers'] = [self.reader()]
        self.assert_unproven(True)

    def test_same_program_in_another_workspace_does_not_cover_root(self):
        other = self.base/'other'; other.mkdir()
        self.plan['readers'] = [self.reader(other)]
        self.assert_unproven(True)

    def nested_roots(self):
        workspace=self.base/'project'; workspace.mkdir()
        first=workspace/'first'; first.mkdir()
        second=workspace/'second'; second.mkdir()
        self.plan['roots']=[{'path':str(p),'program':'plant'} for p in [first,second]]
        self.plan['readers']=[self.reader(workspace)]
        return first, second

    def test_wide_workspace_does_not_implicitly_cover_child_roots(self):
        self.nested_roots()
        self.assert_unproven(True)

    def test_explicit_root_does_not_cover_sibling_root(self):
        first, second=self.nested_roots()
        self.plan['readers'][0]['root']=str(first)
        self.assert_unproven(True)
        self.plan['dry_test_exemptions']=[self.exemption(second)]
        code, verdict=self.check(True)
        self.assertEqual(code, 0)
        self.assertFalse(verdict['unproven_reader_roots'])

    def test_named_lead_exemption_records_exact_root(self):
        self.plan['dry_test_exemptions'] = [self.exemption()]
        code, verdict = self.check()
        self.assertEqual(code, 0)
        self.assertIn('dry_test_exemptions', verdict)
        self.assertEqual(verdict['dry_test_exemptions'][0]['path'], str(self.src))
        self.assertEqual(verdict['dry_test_exemptions'][0]['by'], 'test lead')

    def test_exemption_requires_lead_name_reason_timestamp_and_exact_root(self):
        for changes in [{'by': 'runner'}, {'reason': ''}, {'at': '2026-10-06'},
                        {'path': str(self.base)}, {'by': ''}]:
            with self.subTest(fields=tuple(changes)):
                self.plan['dry_test_exemptions'] = [self.exemption(**changes)]
                self.assert_unproven()

    def test_one_exemption_does_not_cover_another_root(self):
        other = self.base/'other'; other.mkdir()
        self.plan['roots'].append({'path': str(other), 'program': 'plant'})
        self.plan['dry_test_exemptions'] = [self.exemption()]
        self.assert_unproven()

    def test_passing_commands_for_both_roots_allow_clearance(self):
        other = self.base/'other'; other.mkdir()
        self.plan['roots'].append({'path': str(other), 'program': 'plant'})
        self.plan['readers'] = [self.reader(), self.reader(other)]
        code, verdict = self.check(True)
        self.assertEqual(code, 0)
        self.assertIn('unproven_reader_roots', verdict)
        self.assertFalse(verdict['unproven_reader_roots'])
        self.assertEqual(len(verdict['tests']), 4)

    def test_built_reader_command_keeps_baseline_pass_and_rename_failure(self):
        self.plan['readers'] = [self.reader()]
        (self.src/'probe.py').write_text('import pathlib,sys\nbase=pathlib.Path(sys.argv[1]).parent\n(base / ("rules" + ".yaml")).read_text()\n')
        code, verdict = self.check(True)
        self.assertEqual(code, 1)
        self.assertEqual([(t['mode'], t['exit_code']) for t in verdict['tests']], [('baseline', 0), ('renamed', 1)])
        self.assertEqual(self.target.read_text(), 'synthetic\n')

    def test_exemption_never_clears_found_reader(self):
        (self.src/'r.py').write_text('open("rules.yaml")\n')
        self.plan['dry_test_exemptions'] = [self.exemption()]
        code, verdict = self.check()
        self.assertEqual(code, 1)
        self.assertTrue(verdict['blocking_readers'])

    def test_empty_command_array_is_not_a_dry_test(self):
        reader = self.reader(); reader['commands'] = [[]]
        self.plan['readers'] = [reader]
        code, verdict = self.check(True)
        self.assertNotEqual(code, 0)
        self.assertFalse(verdict['tests'])


if __name__ == '__main__':
    unittest.main()
