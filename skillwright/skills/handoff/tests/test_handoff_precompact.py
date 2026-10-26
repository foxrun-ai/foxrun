"""handoff-precompact writes a handoff before compaction, lists unpromoted settlements, and never blocks."""

import json
from datetime import datetime
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest


HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parents[0] / "bin" / "handoff-precompact"
FIXTURES = HERE / "fixtures"
SESSION = "11111111-2222-3333-4444-555555555555"
CHECK = Path(os.path.expanduser(os.environ.get(
    "FOXRUN_HANDOFF_CHECK", "~/.foxrun/memory/handoff_check.py")))


def check_supports_settlements():
    if not CHECK.is_file():
        return False
    helped = subprocess.run([sys.executable, str(CHECK), "--help"], capture_output=True, text=True, check=False)
    return "--settlements" in helped.stdout and "--transcript" in helped.stdout


HAS_CHECK = check_supports_settlements()


class HandoffPrecompactTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        root = Path(self.folder.name)
        self.vault = root / "vault"
        self.workspace = self.vault / "foxrun-dev"
        (self.workspace / "history" / "handoffs").mkdir(parents=True)
        # A temporary tracker built from the stub; the live tracker is never opened for writes.
        self.db = self.workspace / "data.db"
        with sqlite3.connect(self.db) as conn:
            conn.executescript((FIXTURES / "tracker.sql").read_text(encoding="utf-8"))

    def tearDown(self):
        self.folder.cleanup()

    def hook(self, fixture, **extra):
        payload = {"session_id": SESSION, "transcript_path": str(FIXTURES / fixture),
                   "cwd": str(self.workspace), "hook_event_name": "PreCompact", "trigger": "auto",
                   "custom_instructions": None, **extra}
        return json.dumps(payload)

    def run_hook(self, *args, stdin="", check=None):
        environment = {key: value for key, value in os.environ.items() if key != "FOXRUN_SEAT"}
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--vault", str(self.vault), "--check", str(check or CHECK),
             "--db", str(self.db), *args],
            input=stdin, capture_output=True, text=True, env=environment, check=False,
        )

    def test_open_empty_stdin_does_not_hang(self):
        # stdin left open and never written (an agent shell) must not block the script.
        environment = {key: value for key, value in os.environ.items() if key != "FOXRUN_SEAT"}
        process = subprocess.Popen(
            [sys.executable, str(SCRIPT), "--vault", str(self.vault), "--check", str(CHECK), "--db", str(self.db),
             "--seat", "architect", "--cwd", str(self.workspace), "--dry-run", "--json"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=environment,
        )
        try:
            # wait(), not communicate(): communicate closes stdin, which would hide the bug.
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            self.fail("handoff-precompact blocked on an open, empty stdin")
        finally:
            process.stdin.close()
            process.stdout.close()
            process.stderr.close()
        self.assertEqual(process.returncode, 0)

    def handoffs(self):
        return sorted(p for p in (self.workspace / "history" / "handoffs").glob("*.md"))

    @unittest.skipUnless(HAS_CHECK, "handoff_check.py with --settlements and --transcript not found")
    def test_dirty_transcript_lists_unpromoted_and_warns(self):
        before = self.db.stat().st_mtime_ns
        result = self.run_hook("--seat", "architect", stdin=self.hook("dirty.jsonl"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.db.stat().st_mtime_ns, before)
        [path] = self.handoffs()
        self.assertRegex(path.name, r"^\d{4}-\d\d-\d\d-001-architect-precompact\.md$")
        text = path.read_text(encoding="utf-8")
        self.assertIn("## Unpromoted", text)
        self.assertIn("0. Boot Foxrun: `python3 ~/.foxrun/foxrun.py start --workspace foxrun-dev --seat architect`", text)
        self.assertIn("From now on every seat writes its own handoff before compaction", text)
        self.assertRegex(text, r"- 2026-09-2[78] \d\d:03:00 \w+ \(U00\d\): “From now on")
        self.assertIn("seat: architect", text)
        self.assertIn(f"session: {SESSION}", text)
        self.assertIn("Written by the pre-compaction hook (trigger: auto)", text)
        self.assertNotIn("Ruled: handoff", text.split("## Unpromoted")[1].split("## Boot Order")[0])
        for section in ("## Boot Order", "## State", "## Open Items", "## Context", "## Lessons",
                        "## Snapshot", "## Without The Database"):
            self.assertIn(section, text)
        warning = json.loads(result.stdout)["systemMessage"]
        self.assertIn("1 @Person@ settlement has no row", warning)
        self.assertEqual(len(result.stdout.strip().splitlines()), 1)

    @unittest.skipUnless(HAS_CHECK, "handoff_check.py with --settlements and --transcript not found")
    def test_clean_transcript_writes_normal_handoff_without_warning(self):
        result = self.run_hook(stdin=self.hook("clean.jsonl"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        [path] = self.handoffs()
        self.assertTrue(path.name.endswith("-001-precompact.md"))
        text = path.read_text(encoding="utf-8")
        self.assertNotIn("## Unpromoted", text)
        self.assertIn("decision `g-handoff-one-shape`", text)
        self.assertIn("- T286", text.split("## Open Items")[1].split("## Context")[0])
        self.assertIn("tags: [precompact]", text)

    @unittest.skipUnless(HAS_CHECK, "handoff_check.py with --settlements and --transcript not found")
    def test_dry_run_writes_nothing(self):
        result = self.run_hook("--dry-run", stdin=self.hook("dirty.jsonl"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.handoffs(), [])
        self.assertEqual(list((self.workspace / "history" / "handoffs").iterdir()), [])
        self.assertIn("dry run: would write", result.stdout)
        self.assertIn("## Unpromoted", result.stdout)

    @unittest.skipUnless(HAS_CHECK, "handoff_check.py with --settlements and --transcript not found")
    def test_second_run_checks_only_since_the_last_handoff(self):
        self.run_hook(stdin=self.hook("dirty.jsonl"))
        [first] = self.handoffs()
        text = first.read_text(encoding="utf-8")
        stamp = text.split("timestamp: ")[1].split("\n")[0]
        # Move the first note's time past the dirty turn (23:03Z), as if the handoff came after it.
        first.write_text(text.replace(f"timestamp: {stamp}", "timestamp: 2026-09-27T23:05:00+00:00"), encoding="utf-8")
        result = self.run_hook(stdin=self.hook("dirty.jsonl"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        second = self.handoffs()[-1]
        self.assertNotEqual(first, second)
        second_text = second.read_text(encoding="utf-8")
        self.assertIn(f"supersedes: foxrun-dev/history/handoffs/{first.name}", second_text)
        self.assertIn("since 2026-09-27T23:05:00+00:00", second_text)
        self.assertNotIn("## Unpromoted", second_text)

    @unittest.skipUnless(HAS_CHECK, "handoff_check.py with --settlements and --transcript not found")
    def test_handwritten_handoff_is_linked_never_superseded(self):
        today = datetime.now().astimezone().date().isoformat()
        lead = self.workspace / "history" / "handoffs" / f"{today}-001-architect-lead.md"
        lead.write_text(f"---\nsession: {SESSION}\nseat: architect\ntimestamp: 2026-09-27T23:05:00+00:00\n---\n",
                        encoding="utf-8")
        result = self.run_hook("--seat", "architect", "--dry-run", "--json",
                               stdin=self.hook("dirty.jsonl"))
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertIsNone(report["supersedes"])
        self.assertEqual(report["lead_handoff"], f"foxrun-dev/history/handoffs/{lead.name}")
        self.assertIn(f"Lead handoff: `foxrun-dev/history/handoffs/{lead.name}`", report["text"])
        self.assertNotIn("supersedes:", report["text"])
        self.assertIn("## Lessons\n", report["text"])
        self.assertNotIn("To Codify", report["text"])

    @unittest.skipUnless(HAS_CHECK, "handoff_check.py with --settlements and --transcript not found")
    def test_boot_order_lists_handwritten_then_earlier_notes(self):
        today = datetime.now().astimezone().date().isoformat()
        handoffs = self.workspace / "history" / "handoffs"
        old = handoffs / f"{today}-001-architect-precompact.md"
        lead = handoffs / f"{today}-002-architect-lead.md"
        first = handoffs / f"{today}-003-architect-precompact.md"
        second = handoffs / f"{today}-004-architect-precompact.md"
        for path in (old, first, second):
            path.write_text(f"---\nsession: {SESSION}\nseat: architect\ntags: [precompact]\n---\n", encoding="utf-8")
        lead.write_text(f"---\nsession: {SESSION}\nseat: architect\n---\n", encoding="utf-8")
        result = self.run_hook("--seat", "architect", "--dry-run", "--json", stdin=self.hook("clean.jsonl"))
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["earlier_notes"], [f"foxrun-dev/history/handoffs/{first.name}", f"foxrun-dev/history/handoffs/{second.name}"])
        step = [line for line in report["text"].splitlines() if line.startswith("3. Contracts")][0]
        self.assertEqual(step, "3. Contracts, in order: `foxrun-dev/AGENTS.md`, then the hand-written handoff "
                               f"`foxrun-dev/history/handoffs/{lead.name}`, then `foxrun-dev/history/handoffs/{first.name}`, "
                               f"then `foxrun-dev/history/handoffs/{second.name}`, then this note.")

    @unittest.skipUnless(HAS_CHECK, "handoff_check.py with --settlements and --transcript not found")
    def test_created_tasks_and_only_open_titled_rows(self):
        result = self.run_hook("--dry-run", "--json", "--seat", "architect",
                               stdin=self.hook("created.jsonl"))
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        text = report["text"]
        items = text.split("## Open Items\n", 1)[1].split("## Context", 1)[0]
        for task_id, title in (("T301", "Context meter skill"), ("T302", "Archiving and memory decay"),
                               ("T303", "Presentation patterns in the base soul")):
            self.assertIn(f"- {task_id} · {title}\n", items)
            self.assertIn(task_id, report["open_ids"])
        for task_id in ("T304", "T305", "T306"):
            self.assertNotIn(task_id, text)
            self.assertNotIn(task_id, report["open_ids"])
        self.assertNotIn("Touched tasks:", text)

    def test_dirty_replay_uses_placeholder_model_and_remains_read_only(self):
        replay = json.loads((HERE.parent / "replays/precompact-dirty-dry-run.json").read_text())
        check = Path(self.folder.name) / "replay-check.py"
        check.write_text(replay["setup"]["files"]["check.py"])
        checked = subprocess.run([sys.executable, str(check), "--settlements", "--transcript", "fixture"],
                                 capture_output=True, text=True, check=True)
        model = json.loads(checked.stdout)["model"]
        self.assertTrue(model.startswith("fixture-"), model)
        self.assertNotIn(model, {"judgment", "work", "cheap", "code"})
        self.assertNotRegex(model, r"^(gpt-|claude-)")
        before = self.db.read_bytes()
        result = self.run_hook("--dry-run", "--json", "--seat", "architect",
                               stdin=self.hook("dirty.jsonl"), check=check)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(model, report["text"])
        self.assertIn("## Unpromoted", report["text"])
        self.assertIn("1 @Person@ settlement has no row", report["warning"])
        self.assertEqual(self.db.read_bytes(), before)
        self.assertEqual(list((self.workspace / "history/handoffs").iterdir()), [])

    def test_bad_stdin_exits_zero_with_one_line(self):
        result = self.run_hook(stdin="not json")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertEqual(len(result.stderr.strip().splitlines()), 1)
        self.assertEqual(self.handoffs(), [])

    def test_missing_check_still_writes_handoff_and_exits_zero(self):
        result = self.run_hook(stdin=self.hook("dirty.jsonl"), check=Path(self.folder.name) / "absent.py")
        self.assertEqual(result.returncode, 0, result.stderr)
        [path] = self.handoffs()
        self.assertIn("The settlement check did not run: check not found", path.read_text(encoding="utf-8"))

    def test_subagent_and_outside_vault_write_nothing(self):
        for stdin in (self.hook("dirty.jsonl", agent_id="a1"), self.hook("dirty.jsonl", cwd="/")):
            result = self.run_hook(stdin=stdin)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(len(result.stderr.strip().splitlines()), 1)
        self.assertEqual(self.handoffs(), [])


if __name__ == "__main__":
    unittest.main()
