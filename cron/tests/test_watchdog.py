#!/usr/bin/env python3
"""The independent watchdog measures launchd and the last nightly receipt."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

CRON = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CRON))
import watchdog  # noqa: E402


class WatchdogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="nightly-watchdog-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "runs").mkdir()
        (self.root / "config").mkdir()
        (self.root / "config/dream.json").write_text(json.dumps({"interval_seconds": 60}))
        self.now = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)
        self.calls = []

    def receipt(self, age, code=0, steps=None):
        at = (self.now - timedelta(seconds=age)).strftime("%Y%m%dT%H%M%S%fZ")
        # T755: receipts live in runs/nightly/; the watchdog also reads one left at the top of runs/.
        folder = self.root / "runs" / ("nightly" if age % 2 == 0 else "") / (at + "-nightly")
        folder.mkdir(parents=True)
        body = {"at": at, "exit": code}
        if steps is not None:
            body["steps"] = steps
        (folder / "receipt.json").write_text(json.dumps(body))

    def runner(self, code):
        def run(command, **_):
            self.calls.append(command)
            return subprocess.CompletedProcess(command, code, stdout="", stderr="")
        return run

    def notifier(self, command, **_):
        self.calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    def test_stopped_job_delivers_one_alert_from_measured_launchctl_state(self):
        self.receipt(200)
        row = watchdog.check(self.root, "com.foxrun.test-nightly", now=self.now,
                             runner=self.runner(113), notifier=self.notifier)
        self.assertEqual((row["scheduler_loaded"], row["launchctl_exit"], row["notified"]),
                         (False, 113, True))
        alert = json.loads(next((self.root / "runs/nightly").glob("*-nightly-watchdog/alert.json")).read_text())
        self.assertTrue(alert["while_scheduler_dead"])
        self.assertGreaterEqual(alert["receipt_age_seconds"], alert["window_seconds"])
        self.assertTrue(alert["delivered"])
        self.assertEqual(alert["source"], "nightly-watchdog")
        self.assertEqual(self.calls[0][1:3], ["print", "gui/%d/com.foxrun.test-nightly" % __import__('os').getuid()])
        self.assertEqual(self.calls[1][0], "/usr/bin/osascript")
        second = watchdog.check(self.root, "com.foxrun.test-nightly", now=self.now,
                                runner=self.runner(113), notifier=self.notifier)
        self.assertFalse(second["notified"])
        self.assertEqual(len(self.calls), 3)

    def test_state_is_written_through_a_new_private_file_never_a_planted_link(self):
        self.receipt(200)
        outside = self.root / "outside.txt"
        outside.write_text("keep")
        link = self.root / "runs/nightly-watchdog-state.tmp"
        link.symlink_to(outside)
        watchdog.check(self.root, "com.foxrun.test-nightly", now=self.now,
                       runner=self.runner(113), notifier=self.notifier)
        self.assertEqual(outside.read_text(), "keep")
        self.assertTrue(link.is_symlink())
        state = self.root / "runs/nightly-watchdog-state.json"
        self.assertEqual(json.loads(state.read_text())["signature"], "stopped")
        self.assertEqual(state.stat().st_mode & 0o777, 0o600)
        self.assertEqual([p.name for p in (self.root / "runs").glob(".nightly-watchdog-state.json.*")], [])

    def test_failed_notification_retries_while_job_stays_stopped(self):
        self.receipt(200)
        def failed(command, **_):
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="temporary failure")
        first = watchdog.check(self.root, "com.foxrun.test-nightly", now=self.now,
                               runner=self.runner(113), notifier=failed)
        self.assertFalse(first["notified"])
        second = watchdog.check(self.root, "com.foxrun.test-nightly",
                                now=self.now + timedelta(seconds=1),
                                runner=self.runner(113), notifier=self.notifier)
        self.assertTrue(second["notified"])
        self.assertEqual(len(list((self.root / "runs/nightly").glob("*-nightly-watchdog/alert.json"))), 2)

    def test_loaded_job_with_fresh_receipt_needs_no_alert(self):
        self.receipt(20)
        row = watchdog.check(self.root, "com.foxrun.test-nightly", now=self.now,
                             runner=self.runner(0), notifier=self.notifier)
        self.assertEqual(row["status"], "healthy")
        self.assertFalse(row["notified"])
        self.assertEqual(len(self.calls), 1)

    def test_fresh_receipt_with_failed_step_raises_one_failed_alert(self):
        self.receipt(20, 1, {"lint": {"failed": False}, "push": {"failed": True, "exit": 1}})
        row = watchdog.check(self.root, "com.foxrun.test-nightly", now=self.now,
                             runner=self.runner(0), notifier=self.notifier)
        self.assertEqual((row["status"], row["alarm"], row["notified"]), ("failed", True, True))
        self.assertEqual((row["last_exit"], row["failed_steps"]), (1, ["push"]))
        self.assertIn("Foxrun memory job failed", self.calls[1][2])
        alert = json.loads(next((self.root / "runs/nightly").glob("*-nightly-watchdog/alert.json")).read_text())
        self.assertEqual(alert["failed_steps"], ["push"])
        self.assertFalse(alert["while_scheduler_dead"])
        again = watchdog.check(self.root, "com.foxrun.test-nightly", now=self.now,
                               runner=self.runner(0), notifier=self.notifier)
        self.assertEqual((again["status"], again["notified"]), ("failed", False))
        self.assertEqual(len(self.calls), 3)

    def test_nonzero_exit_without_steps_counts_as_failed(self):
        self.receipt(20, 2)
        row = watchdog.check(self.root, "com.foxrun.test-nightly", now=self.now,
                             runner=self.runner(0), notifier=self.notifier)
        self.assertEqual((row["status"], row["failed_steps"]), ("failed", ["exit 2"]))

    def test_newest_receipt_decides_so_a_later_clean_run_clears_the_failure(self):
        self.receipt(40, 1, {"push": {"failed": True}})
        self.receipt(20, 0, {"push": {"failed": False}})
        row = watchdog.check(self.root, "com.foxrun.test-nightly", now=self.now,
                             runner=self.runner(0), notifier=self.notifier)
        self.assertEqual((row["status"], row["alarm"], row["failed_steps"]), ("healthy", False, []))

    def test_stale_wins_over_failed(self):
        self.receipt(200, 1, {"push": {"failed": True}})
        row = watchdog.check(self.root, "com.foxrun.test-nightly", now=self.now,
                             runner=self.runner(0), notifier=self.notifier)
        self.assertEqual(row["status"], "stale")
        self.assertIn("Foxrun memory job stopped", self.calls[1][2])


if __name__ == "__main__":
    unittest.main()
