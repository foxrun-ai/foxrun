"""Regression tests for handoff_check file and folder output paths."""
import io
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
with patch.dict(os.environ, {"FOXRUN_PERSON": "person"}):
    from memory import handoff_check as hc


class HandoffOutTests(unittest.TestCase):
    def setUp(self):
        person = patch.dict(os.environ, {"FOXRUN_PERSON": "person"})
        person.start()
        self.addCleanup(person.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.transcript = self.root / "fixture.jsonl"
        self.transcript.write_text(json.dumps({
            "type": "assistant", "message": {"model": "fixture-model", "content": []}
        }) + "\n")
        self.handoff = self.root / "handoff.md"
        self.handoff.write_text("# Handoff\n")
        self.db = self.root / "tracker.sqlite"
        with sqlite3.connect(self.db) as conn:
            conn.execute("CREATE TABLE runs (id TEXT, session TEXT, model TEXT)")
        self.data = hc.Extract("fixture", str(self.transcript), model="fixture-model")

    def run_check(self, out, *extra):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = hc.main(["--transcript", str(self.transcript), "--handoff", str(self.handoff),
                              "--db", str(self.db), "--out", str(out), *extra])
        return result, stdout.getvalue(), stderr.getvalue()

    def test_md_path_writes_extract_to_file(self):
        out = self.root / "session.md"
        hc.write_extract(self.data, out)
        self.assertTrue(out.is_file())
        self.assertIn("# Extract: fixture", out.read_text())
        self.assertEqual(sorted(p.name for p in self.root.glob("session*")), ["session.md"])

    def test_file_parent_must_exist(self):
        out = self.root / "missing" / "session.md"
        with self.assertRaises(OSError):
            hc.write_extract(self.data, out)
        self.assertFalse(out.parent.exists())

    def test_suffixless_folder_keeps_all_report_names(self):
        out = self.root / "nested" / "out"
        result, stdout, stderr = self.run_check(out, "--kind", "worker", "--backfill-model", "--dry-run")
        self.assertEqual(result, 0, stderr)
        self.assertEqual(sorted(p.name for p in out.iterdir()),
                         ["backfill-model.md", "extract.md", "worker-did.md"])
        self.assertIn(f"extract={out / 'extract.md'}", stdout)
        self.assertIn(f"worker={out / 'worker-did.md'}", stdout)
        self.assertIn(f"report={out / 'backfill-model.md'}", stdout)

    def test_leftover_md_folder_is_refused_without_writes(self):
        out = self.handoff.with_name(self.handoff.name + ".coverage.md")
        out.mkdir()
        sentinel = out / "extract.md"
        sentinel.write_bytes(b"old extract\n")
        before = {p.relative_to(self.root): p.read_bytes()
                  for p in self.root.rglob("*") if p.is_file()}
        result, stdout, stderr = self.run_check(out, "--backfill-model", "--dry-run")
        self.assertEqual(result, 1)
        self.assertIn(str(out), stderr)
        self.assertIn("directory", stderr.lower())
        self.assertIn("--out", stderr)
        self.assertNotIn("coverage ids=", stdout)
        self.assertTrue(out.is_dir())
        self.assertEqual({p.relative_to(self.root): p.read_bytes()
                          for p in self.root.rglob("*") if p.is_file()}, before)

    def test_worker_report_is_beside_file(self):
        out = self.root / "session.coverage.md"
        result, stdout, stderr = self.run_check(out, "--kind", "worker")
        self.assertEqual(result, 0, stderr)
        self.assertTrue(out.is_file())
        report = self.root / "session.coverage.worker-did.md"
        self.assertIn("# Worker did:", report.read_text())
        self.assertIn(f"extract={out}", stdout)
        self.assertIn(f"worker={report}", stdout)

    def test_backfill_report_is_beside_file(self):
        out = self.root / "session.coverage.md"
        result, stdout, stderr = self.run_check(out, "--backfill-model", "--dry-run")
        self.assertEqual(result, 0, stderr)
        self.assertTrue(out.is_file())
        report = self.root / "session.coverage.backfill-model.md"
        self.assertIn("# Model backfill", report.read_text())
        self.assertIn("Mode: dry run", report.read_text())
        self.assertIn(f"report={report}", stdout)

    def test_reports_replace_a_planted_link_and_never_write_through_it(self):
        out = self.root / "out"
        out.mkdir()
        outside = self.root / "outside.txt"
        outside.write_text("keep")
        for name in ("extract.md", "worker-did.md", "backfill-model.md"):
            (out / name).symlink_to(outside)
        result, stdout, stderr = self.run_check(out, "--kind", "worker", "--backfill-model", "--dry-run")
        self.assertEqual(result, 0, stderr)
        self.assertEqual(outside.read_text(), "keep")
        for name in ("extract.md", "worker-did.md", "backfill-model.md"):
            report = out / name
            self.assertFalse(report.is_symlink(), name)
            self.assertEqual(report.stat().st_mode & 0o777, 0o600, name)
        self.assertEqual(sorted(p.name for p in out.iterdir()), ["backfill-model.md", "extract.md", "worker-did.md"])
        coverage = self.handoff.with_name(self.handoff.name + ".coverage.md")
        coverage.symlink_to(outside)
        result, stdout, stderr = self.run_check(self.root / "lead", "--kind", "lead")
        self.assertEqual(result, 0, stderr)
        self.assertEqual(outside.read_text(), "keep")
        self.assertFalse(coverage.is_symlink())
        self.assertEqual(coverage.stat().st_mode & 0o777, 0o644)

    def test_backfill_backup_is_a_new_private_file(self):
        with sqlite3.connect(self.db) as conn:
            conn.execute("INSERT INTO runs VALUES ('R1', 'session-fixture-1', 'unknown')")
        with patch.object(hc, "transcript", return_value=self.transcript):
            statements, backup = hc.backfill(self.db, dry_run=False)
        self.assertEqual(len(statements), 1)
        self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
        with sqlite3.connect(backup) as conn:
            self.assertEqual(conn.execute("SELECT model FROM runs").fetchone(), ("unknown",))
        with sqlite3.connect(self.db) as conn:
            self.assertEqual(conn.execute("SELECT model FROM runs").fetchone(), ("fixture-model",))
        self.assertEqual(sorted(p.name for p in self.root.iterdir() if p.name.startswith(".")), [])

    def test_lead_prints_coverage_with_file_output(self):
        out = self.handoff.with_name(self.handoff.name + ".coverage.md")
        result, stdout, stderr = self.run_check(out, "--kind", "lead")
        self.assertEqual(result, 0, stderr)
        self.assertTrue(out.is_file())
        self.assertIn("# Handoff coverage:", out.read_text())
        self.assertIn("coverage ids=100% files=100% gaps=0", stdout)
        self.assertIn("settlements=0", stdout)
        self.assertIn(f"extract={out}\n", stdout)


if __name__ == "__main__":
    unittest.main()
