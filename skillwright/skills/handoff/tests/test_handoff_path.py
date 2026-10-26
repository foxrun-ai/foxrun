"""Atomic handoff path reservation checks."""

from datetime import datetime
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "bin" / "handoff-path"


class HandoffPathTests(unittest.TestCase):
    def test_timestamp_reads_clock_and_formats_offset(self):
        before = datetime.now().astimezone()
        result = subprocess.run([sys.executable, str(SCRIPT), "--timestamp"], capture_output=True,
                                text=True, check=True)
        after = datetime.now().astimezone()
        stamp = datetime.fromisoformat(result.stdout.strip())
        self.assertRegex(result.stdout.strip(), r"[+-]\d\d:\d\d$")
        self.assertLessEqual(before.replace(microsecond=0), stamp)
        self.assertLessEqual(stamp, after)

    def test_parallel_different_subjects_get_distinct_numbers(self):
        with tempfile.TemporaryDirectory() as folder:
            calls = [
                subprocess.Popen(
                    [sys.executable, str(SCRIPT), folder, f"subject-{index}"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                for index in range(8)
            ]
            results = [call.communicate() for call in calls]
            for call, (_, error) in zip(calls, results):
                self.assertEqual(call.returncode, 0, error)
            paths = [Path(output.strip()) for output, _ in results]
            today = datetime.now().astimezone().date().isoformat()
            self.assertEqual(
                {path.name.split("-")[3] for path in paths},
                {f"{number:03d}" for number in range(1, 9)},
            )
            self.assertEqual(len(set(paths)), 8)
            for number in range(1, 9):
                self.assertTrue((Path(folder) / "history" / "handoffs" / f".{today}-{number:03d}.reserved").is_file())

    def test_parallel_calls_get_different_numbers(self):
        with tempfile.TemporaryDirectory() as folder:
            calls = [
                subprocess.Popen(
                    [sys.executable, str(SCRIPT), folder, "lead-close"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                for _ in range(2)
            ]
            results = [call.communicate() for call in calls]
            for call, (_, error) in zip(calls, results):
                self.assertEqual(call.returncode, 0, error)
            paths = [Path(output.strip()) for output, _ in results]
            self.assertEqual(len(set(paths)), 2)
            self.assertEqual({path.stat().st_size for path in paths}, {0})
            self.assertEqual({path.name.split("-")[3] for path in paths}, {"001", "002"})

    def test_existing_number_is_skipped(self):
        with tempfile.TemporaryDirectory() as folder:
            handoffs = Path(folder) / "history" / "handoffs"
            handoffs.mkdir(parents=True)
            today = datetime.now().astimezone().date().isoformat()
            existing = handoffs / f"{today}-001-lead-close.md"
            existing.write_text("keep")
            result = subprocess.run(
                [sys.executable, str(SCRIPT), folder, "lead-close"],
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertEqual(Path(result.stdout.strip()).name, f"{today}-002-lead-close.md")
            self.assertEqual(existing.read_text(), "keep")

    def test_bad_subject_is_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            result = subprocess.run(
                [sys.executable, str(SCRIPT), folder, "Bad/Subject"],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("subject must be lowercase kebab-case", result.stderr)
            self.assertFalse((Path(folder) / "history" / "handoffs").exists())


if __name__ == "__main__":
    unittest.main()
