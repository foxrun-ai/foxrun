"""T757/T758: fail-closed requests, rule dispositions, and contract discovery on fake homes."""
import contextlib
import csv
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
import lint as engine
import lint_gate as gate


def page(workspace, body='# Note\n\nA labeled fixture note.\n'):
    return '---\ntype: doc\nworkspace: '+workspace+'\ntimestamp: 2026-10-20T12:00:00-04:00\n---\n'+body


class WriteContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve(); self.home = self.root/'system'; self.portfolio = self.root/'portfolio'
        self.policy = self.home/'config/lint'
        shutil.copytree(BASE.parent/'config/lint', self.policy)
        (self.portfolio/'shop/notes').mkdir(parents=True)
        (self.portfolio/'shop/AGENTS.md').write_text(page('shop', '# Shop\n'))
        (self.policy/'db.tsv').write_text('home\tpath\ttable\tcolumn\tformat\n')
        self.rule('warning')
        self.target = self.portfolio/'shop/notes/example.md'
        self.draft = self.root/'draft.md'; self.draft.write_text(page('shop'))

    def rule(self, disposition):
        (self.policy/'rules.tsv').write_text('id\twords\tkind\tscope\tlevel\twrite\n'
            'FM\tFixture frontmatter.\tfrontmatter\tworkspace:**/*.md\terror\t'+disposition+'\n')

    def request(self, body=None, target=None):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            status = gate.main(['--mode','write','--home',str(self.home),'--workspaces',str(self.portfolio),
                                '--target',str(target or self.target),'--body',str(body or self.draft)])
        return status, stdout.getvalue(), stderr.getvalue()

    def snapshot(self):
        return {str(p.relative_to(self.root)):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}

    def test_invalid_body_fails_closed_and_writes_nothing(self):
        directory = self.root/'directory'; directory.mkdir()
        invalid = self.root/'invalid.bin'; invalid.write_bytes(b'\xff\xfe')
        link = self.root/'linked.md'; link.symlink_to(self.draft)
        secret = self.root/'.env'; secret.write_text('Labeled fake data\n')
        for body in ['# inline proposed text', self.root/'missing.md', directory, invalid, link, secret]:
            with self.subTest(body=body):
                before = self.snapshot(); status, out, error = self.request(body)
                self.assertNotEqual(status, 0); self.assertIn('FAIL lint gate', error)
                self.assertEqual(out, ''); self.assertEqual(before, self.snapshot())
        self.assertIn('path to an existing', self.request('# Inline text')[2])

    def test_directory_target_fails_even_outside_rule_scopes(self):
        target=self.home/'outside-scope';target.mkdir()
        before=self.snapshot();status,out,error=self.request(target=target)
        self.assertNotEqual(status,0);self.assertIn('regular file',error)
        self.assertEqual(before,self.snapshot())

    def test_excluded_regular_file_has_no_page_checks_but_bad_python_is_refused(self):
        target=self.home/'outside.py'
        self.draft.write_text('print("Labeled fixture")\n')
        self.assertEqual(self.request(target=target)[0],0)
        self.draft.write_text('def broken(\n')
        self.assertNotEqual(self.request(target=target)[0],0)
        self.assertFalse(target.exists())

    def test_bad_policy_fails_closed(self):
        self.rule('misspelled')
        before = self.snapshot(); self.assertNotEqual(self.request()[0], 0)
        self.assertEqual(before, self.snapshot())

    def test_warning_allows_and_blocking_refuses_same_bytes(self):
        self.draft.write_text('# Missing frontmatter\n')
        before = self.snapshot(); status, out, _ = self.request()
        self.assertEqual(status, 0); findings = json.loads(out)
        self.assertTrue(findings); self.assertEqual({r['write'] for r in findings}, {'warning'})
        self.assertEqual(before, self.snapshot())
        self.rule('blocking'); before = self.snapshot(); status, out, _ = self.request()
        self.assertEqual(status, 1); self.assertEqual({r['write'] for r in json.loads(out)}, {'blocking'})
        self.assertEqual(before, self.snapshot())

    def test_fifty_line_note_scopes_inputs_and_finishes_under_five_seconds(self):
        self.draft.write_text(page('shop', '# Note\n'+'A labeled timing line.\n'*44))
        self.assertEqual(len(self.draft.read_text().splitlines()), 50)
        unrelated = self.portfolio/'shop/raw/large.bin'; unrelated.parent.mkdir(); unrelated.write_bytes(b'x'*1000000)
        copyfile = shutil.copyfile; copied = []
        def copy(source, destination, *args, **kwargs):
            copied.append(Path(source)); self.assertNotEqual(Path(source), unrelated)
            return copyfile(source, destination, *args, **kwargs)
        start = time.perf_counter()
        with patch.object(engine.Lint, 'inventory', side_effect=AssertionError('Full inventory forbidden')), patch.object(gate.shutil,'copyfile',side_effect=copy):
            status, out, error = self.request()
        self.assertEqual(status, 0, error); self.assertEqual(json.loads(out), [])
        self.assertLess(time.perf_counter()-start, 5); self.assertFalse(self.target.exists())
        self.assertEqual(copied,[])

    def test_new_contract_registers_first_save_and_nightly_findings(self):
        fresh = self.portfolio/'fresh'; fresh.mkdir(); (fresh/'AGENTS.md').write_text(page('fresh', '# Fresh\n'))
        target = fresh/'notes/first.md'
        before_registry = (self.policy/'workspaces.tsv').read_bytes()
        self.rule('blocking'); self.draft.write_text(page('fresh'))
        self.assertIn('fresh', engine.Lint(self.home,self.portfolio,self.policy).names)
        status, out, error = self.request(target=target)
        self.assertEqual(status, 0, out+error); self.assertEqual(json.loads(out), [])
        self.assertFalse(target.exists()); self.assertEqual(before_registry,(self.policy/'workspaces.tsv').read_bytes())
        # Simulate the authorized save. A later warning must appear in Keeper's actual report.
        target.parent.mkdir(); target.write_text('# Missing frontmatter\n'); self.rule('warning')
        for name in ('lint.py','paths.py'):
            dest = self.home/'base'/name; dest.parent.mkdir(exist_ok=True); shutil.copyfile(BASE/name,dest)
        sys.path.insert(0,str(BASE.parent/'cron'))
        import nightly
        failed, count = nightly.run_lint(self.home,self.portfolio)
        self.assertFalse(failed); self.assertGreater(count,0)
        reports = list((self.home/'runs/nightly').glob('*-lint/findings.json')); self.assertEqual(len(reports),1)
        findings = json.loads(reports[0].read_text())
        self.assertTrue(any(r['path']==str(target) and r['write']=='warning' and r['rule_id']=='FM' for r in findings))

    def test_new_workspace_first_save_with_all_shipped_rules(self):
        fresh=self.portfolio/'fresh';fresh.mkdir();(fresh/'AGENTS.md').write_text(page('fresh'))
        shutil.copyfile(BASE.parent/'config/lint/rules.tsv',self.policy/'rules.tsv')
        self.draft.write_text(page('fresh'))
        status,out,error=self.request(target=fresh/'notes/first.md')
        self.assertEqual(status,0,error)
        self.assertFalse(any('Invalid front matter value: workspace' in r['what'] for r in json.loads(out)))

    def test_uncontracted_and_linked_contracts_do_not_register(self):
        (self.portfolio/'loose').mkdir(); (self.portfolio/'alias').symlink_to('shop')
        (self.portfolio/'linked-contract').mkdir(); (self.portfolio/'linked-contract/AGENTS.md').symlink_to(self.portfolio/'shop/AGENTS.md')
        names = engine.Lint(self.home,self.portfolio,self.policy).names
        self.assertEqual(names, {'shop','alias'})


if __name__=='__main__':unittest.main()
