
from __future__ import annotations

import sys as _fox_sys
from pathlib import Path as _FoxPath
_fox_root = next(p for p in _FoxPath(__file__).resolve().parents if (p / 'base/core.py').is_file())
_fox_sys.path[:0] = [str(_fox_root / p) for p in ('base', 'work', 'events', 'decisions', 'memory', 'people', 'design', 'capture')]
_fox_sys.path.insert(0, str(_fox_root))
from base.tests.support import setup as _fox_test_setup
_fox_test_setup()
import json
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest
import importlib.util


SCRIPT = (Path(__file__).resolve().parent / '../../events/log_switch.py')
SPEC = importlib.util.spec_from_file_location("log_switch", SCRIPT)
LOG_SWITCH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LOG_SWITCH)


SAMPLE = """---
type: log
workspace: sample
---
# sample log

- 2026-09-18T10:00:00-04:00 — done · agent: sol · Shipped the parser.

## 2026-09-17 - Earlier work

- [progress] Kept the body.

## Undated source

- [timestamp] 2026-09-16T09:00:00-04:00
- [source] Preserved the source.
"""


class LogSwitchTest(unittest.TestCase):
    def test_dry_run_writes_jsonl_and_counts_every_content_line(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "sample"
            workspace.mkdir()
            (workspace / "log.md").write_text(SAMPLE)
            output = root / "log.jsonl"
            result = subprocess.run(
                [sys.executable, str(SCRIPT), str(workspace), "--dry-run", "--out", str(output)],
                check=True, capture_output=True, text=True,
            )
            rows = [json.loads(line) for line in output.read_text().splitlines()]
            self.assertEqual(3, len(rows))
            self.assertIn("entries parsed: 3", result.stdout)
            self.assertIn("lines not accounted for: 6", result.stdout)
            self.assertEqual("sol", rows[0]["agent"])
            self.assertEqual("progress", rows[1]["tag"])
            self.assertEqual("2026-09-16T09:00:00-04:00", rows[2]["date"])
            self.assertEqual({"start": 7, "end": 8}, rows[0]["source_line_range"])

    def test_refuses_without_dry_run_and_preserves_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "sample"
            workspace.mkdir()
            source = workspace / "log.md"
            source.write_text(SAMPLE)
            output = root / "log.jsonl"
            result = subprocess.run(
                [sys.executable, str(SCRIPT), str(workspace), "--out", str(output)],
                capture_output=True, text=True,
            )
            self.assertNotEqual(0, result.returncode)
            self.assertFalse(output.exists())
            self.assertEqual(SAMPLE, source.read_text())

    def test_lists_each_unaccounted_line(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "sample"
            workspace.mkdir()
            source = SAMPLE.replace("# sample log\n", "# sample log\nstray legacy text\n")
            (workspace / "log.md").write_text(source)
            output = root / "log.jsonl"
            result = subprocess.run(
                [sys.executable, str(SCRIPT), str(workspace), "--dry-run", "--out", str(output)],
                check=True, capture_output=True, text=True,
            )
            self.assertIn("lines not accounted for: 7", result.stdout)
            self.assertIn("unaccounted line 6: stray legacy text", result.stdout)

    def test_artifact_markers_start_the_following_receipt(self):
        source = """## 2026-09-08T09:16:45+00:00 — Workspace checkpoint
<!-- workspace-close:close-cd0e995c -->
<!-- workspace-artifact:483625eaf0ce69e9e9210c6f5e5e6065fb6c7ae9772dbc9a302274c489c4344e -->
### 2026-09-08T09:16:30+00:00 — note-create
Artifact: first
## 2026-09-06T23:11:32+00:00 — Workspace checkpoint
<!-- workspace-close:close-fb37845c -->
<!-- workspace-artifact:8c1fe05247054754414f10d807bef62a5441f1bab307e044f165283eb4a3fd52 -->
### 2026-09-06T23:11:05+00:00 — note-create
Artifact: second
"""
        rows, unaccounted = LOG_SWITCH.parse_log(source)
        self.assertEqual([], unaccounted)
        self.assertEqual({"start": 1, "end": 2}, rows[0]["source_line_range"])
        self.assertEqual({"start": 3, "end": 5}, rows[1]["source_line_range"])
        self.assertIn("workspace-artifact:483625", rows[1]["body"])
        self.assertEqual({"start": 6, "end": 7}, rows[2]["source_line_range"])
        self.assertEqual({"start": 8, "end": 10}, rows[3]["source_line_range"])
        self.assertIn("workspace-artifact:8c1fe0", rows[3]["body"])

    def test_mixed_heading_and_inline_receipts_do_not_overlap(self):
        source = """## 2026-09-18 - Heading receipt
- [progress] heading body
- 2026-09-18T10:00:00-04:00 — done · agent: sol · Inline receipt.
inline continuation
## 2026-09-17 - Next heading
- [source] next body
"""
        rows, unaccounted = LOG_SWITCH.parse_log(source)
        self.assertEqual([], unaccounted)
        self.assertEqual(3, len(rows))
        self.assertEqual({"start": 1, "end": 2}, rows[0]["source_line_range"])
        self.assertEqual({"start": 3, "end": 4}, rows[1]["source_line_range"])
        self.assertEqual({"start": 5, "end": 6}, rows[2]["source_line_range"])
        self.assertNotIn("Inline receipt", rows[0]["body"])
        self.assertIn("inline continuation", rows[1]["body"])
        for number in range(1, 7):
            owners = sum(
                row["source_line_range"]["start"] <= number <= row["source_line_range"]["end"]
                for row in rows
            )
            self.assertEqual(1, owners, f"line {number}")

    def test_partition_check_rejects_overlap_and_gap(self):
        overlap = [
            {"source_line_range": {"start": 1, "end": 2}},
            {"source_line_range": {"start": 2, "end": 3}},
        ]
        with self.assertRaisesRegex(RuntimeError, "source partition failed"):
            LOG_SWITCH.validate_partition(3, overlap, [])
        gap = [{"source_line_range": {"start": 1, "end": 1}}]
        with self.assertRaisesRegex(RuntimeError, "source partition failed"):
            LOG_SWITCH.validate_partition(2, gap, [])


if __name__ == "__main__":
    unittest.main()
