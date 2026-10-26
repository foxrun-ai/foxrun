"""T97 does not pass when a runtime is unavailable or skipped."""
import io
import sys
import subprocess
from contextlib import redirect_stdout
from unittest.mock import patch
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from base import t97_grade
from base.t97_grade import task_passes

class T97GradeTests(unittest.TestCase):
    def test_self_test_reads_shipped_rubric_from_any_working_directory(self):
        grader = Path(__file__).resolve().parents[1] / 't97_grade.py'
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, '-B', str(grader), '--self-test'],
                                    cwd=directory, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('Self-test passed: 20', result.stdout)

    def setUp(self):
        self.summaries = [dict(layer=layer, runtime=runtime, result='pass', runtime_status='ran')
                          for layer in ('system', 'portfolio', 'workspace', 'source')
                          for runtime in ('codex', 'claude', 'hermes')]
        self.statuses = {(row['layer'], row['runtime']): dict(status='ran', exit_code='0')
                         for row in self.summaries}

    def test_all_runtime_runs_pass(self):
        self.assertTrue(task_passes(self.summaries, self.statuses))

    def test_hermes_unavailable_fails(self):
        self.statuses['source', 'hermes'] = dict(status='unavailable', exit_code='')
        self.summaries[-1]['runtime_status'] = 'unavailable'
        self.assertFalse(task_passes(self.summaries, self.statuses))

    def test_missing_run_or_failing_answer_fails(self):
        del self.statuses['source', 'hermes']
        self.assertFalse(task_passes(self.summaries, self.statuses))
        self.statuses['source', 'hermes'] = dict(status='ran', exit_code='0')
        self.summaries[-1]['result'] = 'fail'
        self.assertFalse(task_passes(self.summaries, self.statuses))

    def test_report_names_the_grader_not_a_task_id(self):
        shipped = Path(t97_grade.__file__).resolve().parent / 'questions.tsv'
        with tempfile.TemporaryDirectory() as directory:
            job = Path(directory).resolve()
            run = job / 'answers/run-1'
            run.mkdir(parents=True)
            rows = t97_grade.read_tsv(shipped)
            for row in rows:
                row.update(contract_sha256_json='{}', contract_lines='')  # A prepared run adds these.
            t97_grade.write_tsv(run / 'questions.tsv', list(rows[0]), rows)
            (run / 'run-status.tsv').write_text('layer\truntime\tstatus\texit_code\tdetail\n')
            printed = io.StringIO()
            with patch.object(t97_grade, 'JOB', job), patch.object(sys, 'argv', ['grade']), \
                    redirect_stdout(printed):
                self.assertEqual(t97_grade.main(), 1)
            report = (job / 'result.md').read_text()
            rows = (job / 'rows-result.tsv').read_text()
        self.assertTrue(report.startswith('Agent-rules grade: fail.'), report)
        self.assertIn('agent-rules grade\tfail', rows)
        for text in (report, rows, printed.getvalue()):
            self.assertNotIn('T97', text)

if __name__ == '__main__':
    unittest.main()
