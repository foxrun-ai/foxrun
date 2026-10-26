"""Rehearsal checks for imessage-send. No test runs the send path."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


BIN = Path(__file__).resolve().parents[1] / "bin" / "imessage-send"


class RehearsalTests(unittest.TestCase):
    def rehearse(self, *args: str, path: str) -> subprocess.CompletedProcess[str]:
        # PATH holds only a fake imsg that records any call, so a slip can never reach Messages.
        return subprocess.run(
            [sys.executable, str(BIN), "--rehearsal", *args],
            text=True, capture_output=True, stdin=subprocess.DEVNULL, check=False,
            env={**os.environ, "PATH": path},
        )

    def fake_imsg(self, folder: Path) -> Path:
        marker = folder / "imsg-called"
        fake = folder / "imsg"
        fake.write_text(f"#!/bin/sh\ntouch {marker}\n", encoding="utf-8")
        fake.chmod(0o755)
        return marker

    def test_rehearsal_prints_what_would_have_gone_and_never_runs_imsg(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            marker = self.fake_imsg(Path(folder))
            completed = self.rehearse("--to", "replay@example.com", "--text", "Hi, test.", "--no-sms-fallback", path=folder)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            result = json.loads(completed.stdout)
            self.assertEqual(result["would_send"]["text"], "Hi, test.")
            self.assertEqual(result["would_send"]["to"], "replay@example.com")
            self.assertFalse(result["sent"])
            self.assertEqual(
                result["command"],
                ["imsg", "send", "--to", "replay@example.com", "--text", "Hi, test.", "--service", "auto", "--no-sms-fallback"],
            )
            self.assertIn("nothing sent", completed.stderr)
            self.assertFalse(marker.exists())

    def test_rehearsal_checks_the_attachment_and_the_target(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            self.fake_imsg(Path(folder))
            missing = self.rehearse("--chat-id", "7", "--file", str(Path(folder) / "gone.pdf"), path=folder)
            self.assertEqual(missing.returncode, 2)
            self.assertIn("attachment not found", missing.stderr)
            empty = self.rehearse("--to", "replay@example.com", path=folder)
            self.assertEqual(empty.returncode, 2)
            both = self.rehearse("--to", "replay@example.com", "--chat-id", "7", "--text", "x", path=folder)
            self.assertEqual(both.returncode, 2)

    def test_help_answers(self) -> None:
        completed = subprocess.run([sys.executable, str(BIN), "--help"], text=True, capture_output=True, check=False)
        self.assertEqual(completed.returncode, 0)
        self.assertIn("--rehearsal", completed.stdout)


if __name__ == "__main__":
    unittest.main()
