"""Fixture checks for the nightly session action and receipt."""

from __future__ import annotations

import sys as _fox_sys
from pathlib import Path as _FoxPath
_fox_root = next(p for p in _FoxPath(__file__).resolve().parents if (p / 'base/core.py').is_file())
_fox_sys.path[:0] = [str(_fox_root / p) for p in ('base', 'work', 'events', 'decisions', 'memory', 'people', 'design', 'capture')]
_fox_sys.path.insert(0, str(_fox_root))
from base.tests.support import setup as _fox_test_setup
_fox_test_setup()

from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS))
import dream as nightly  # noqa: E402


class SessionNightlyTests(unittest.TestCase):
    def setUp(self):
        person_env = patch.dict(os.environ, {"FOXRUN_DREAM_TASK": "T9"})
        person_env.start()
        self.addCleanup(person_env.stop)
        self.temp = tempfile.TemporaryDirectory(prefix="session-nightly-")
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name).resolve()
        tracker = root / "tracker.sqlite"
        blueprint = ((Path(__file__).resolve().parent / '../blueprint.sql')).read_text(encoding="utf-8")
        with sqlite3.connect(tracker) as db:
            db.executescript(blueprint)
            db.execute("INSERT INTO tasks (id,title) VALUES ('T9','Nightly check')")
            db.execute("INSERT INTO tasks (id,title) VALUES ('T1','Pricing decision')")
        claude = root / "claude/project"
        claude.mkdir(parents=True)
        session = "11111111-2222-3333-4444-555555555555"
        transcript = claude / f"{session}.jsonl"
        rows = [
            {"type": "assistant", "timestamp": "2026-09-29T01:00:00-04:00",
             "message": {"content": "For T1, should I set the pricing rule?"}},
            {"type": "user", "timestamp": "2026-09-29T01:01:00-04:00",
             "message": {"content": "The rule is to keep the new pricing page at twenty nine dollars."}},
        ]
        transcript.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
        receipt_root = root / "system-workspace"
        receipt_root.mkdir()
        self.cfg = nightly.Config(
            tracker=tracker, other_tracker=root / "missing.sqlite", receipt_root=receipt_root,
            output_root=receipt_root / "outputs/nightly", state_file=root / "state/state.json",
            scratch_dir=root / "scratch", claude_root=root / "claude", codex_root=root / "codex",
            now=datetime.fromisoformat("2026-09-29T04:00:00-04:00"),
        )

    def rows(self, sql):
        with sqlite3.connect(self.cfg.tracker) as db:
            return db.execute(sql).fetchall()

    def date_run_as_fixture(self):
        with sqlite3.connect(self.cfg.tracker) as db:
            db.execute("UPDATE runs SET started_at=?", (self.cfg.now.isoformat(),))

    def test_cancelled_spelling_is_closed_for_task_context(self):
        legacy = self.cfg.tracker.parent / "legacy.sqlite"
        with sqlite3.connect(legacy) as db:
            db.execute("CREATE TABLE tasks (id TEXT, status TEXT)")
            db.execute("CREATE TABLE runs (subject_type TEXT, subject_id TEXT, session TEXT)")
            db.execute("INSERT INTO tasks VALUES ('T8','cancelled')")
        open_tasks, _ = nightly.task_context((legacy,))
        self.assertNotIn("T8", open_tasks)

    @staticmethod
    def pass_jev(cfg, items, deadline):
        return {item["key"]: 0.91 for item in items}, 0.002, None

    @staticmethod
    def fail_jev(cfg, items, deadline):
        return {}, None, "Jev not run"

    def test_flag_targets_task_receipt_and_idempotent_rerun(self):
        first = nightly.run_nightly(self.cfg, jev_fn=self.pass_jev)
        self.assertEqual(first["failures"], [])
        self.assertEqual((first["sessions"], first["settlements"], first["recorded"], first["flagged"]),
                         (1, 1, 0, 1))
        flags = self.rows("SELECT subject_id,author,body FROM comments WHERE body LIKE 'Flag:%'")
        self.assertEqual(len(flags), 1)
        self.assertEqual(flags[0][:2], ("T1", "session-nightly"))
        self.assertIn("(Jev 0.910)", flags[0][2])
        self.assertEqual(self.rows("SELECT subject_id,result,evidence FROM runs"),
                         [("T9", "pass", "outputs/nightly/2026-09-29-session-check.md")])
        evidence = self.cfg.output_root / "2026-09-29-session-check.md"
        self.assertIn("Sessions scanned: 1", evidence.read_text())
        self.assertIn("Flagged: 1", evidence.read_text())
        self.assertIn("0.910", evidence.read_text())
        self.assertTrue(evidence.read_text().startswith("---\ntype: receipt\nworkspace: system-workspace\n"))
        self.assertIn("scan_end=", self.rows("SELECT note FROM runs")[0][0])
        state = json.loads(self.cfg.state_file.read_text())
        self.assertEqual(len(state["flagged"]), 1)
        self.date_run_as_fixture()
        second = nightly.run_nightly(self.cfg, jev_fn=self.pass_jev)
        self.assertTrue(second["already_ran"])
        self.assertEqual(len(self.rows("SELECT id FROM runs")), 1)
        self.assertEqual(len(self.rows("SELECT id FROM comments WHERE body LIKE 'Flag:%'")), 1)

    def test_jev_failure_keeps_item_ends_fail_and_opens_one_bug(self):
        result = nightly.run_nightly(self.cfg, jev_fn=self.fail_jev)
        self.assertIn("Jev not run", result["failures"])
        self.assertEqual(result["flagged"], 1)
        flag = self.rows("SELECT subject_id,body FROM comments WHERE body LIKE 'Flag:%'")[0]
        self.assertEqual(flag[0], "T1")
        self.assertIn("(Jev not run)", flag[1])
        self.assertEqual(self.rows("SELECT result FROM runs"), [("fail",)])
        self.assertEqual(len(self.rows("SELECT id FROM bugs")), 1)
        self.date_run_as_fixture()
        again = nightly.run_nightly(self.cfg, jev_fn=self.fail_jev)
        self.assertTrue(again["already_ran"])
        self.assertEqual(len(self.rows("SELECT id FROM bugs")), 1)
        self.assertEqual(len(self.rows("SELECT id FROM comments WHERE body LIKE 'Flag:%'")), 1)

    def test_dry_run_does_not_write_tracker_state_or_receipt(self):
        self.cfg.dry_run = True
        result = nightly.run_nightly(self.cfg, jev_fn=self.pass_jev)
        self.assertEqual((result["items"], result["flagged"]), (1, 1))
        self.assertEqual(self.rows("SELECT count(*) FROM runs"), [(0,)])
        self.assertEqual(self.rows("SELECT count(*) FROM comments"), [(0,)])
        self.assertFalse(self.cfg.state_file.exists())
        self.assertFalse(self.cfg.output_root.exists())
        self.assertFalse(self.cfg.scratch_dir.exists())

    def test_dry_jev_uses_batch_with_temporary_storage(self):
        self.cfg.dry_run = True
        item = {"key": "sample", "assistant_before": "Should I run it?",
                "text": "Yes", "task": "T1"}
        storage = []

        def fake_run(command, **kwargs):
            request = json.loads(kwargs["input"])
            self.assertEqual(request["action"], "batch")
            self.assertIn("--resume", command)
            row = request["requests"][0]
            self.assertNotIn("possible_instruction", row["state"])
            self.assertIn("standing rule", row["questions"]["keep"]["instructions"])
            database = Path(row["storage"]["database"])
            self.assertTrue(database.exists())
            storage.append(database)
            progress = Path(command[command.index("--progress") + 1])
            progress.write_text(json.dumps({"ok": True, "request_id": row["request_id"],
                                            "result": {"answers": {"keep": {"probability": 0.12}},
                                                       "provider_cost": {"amount": 0.001}}}) + "\n")
            return type("Result", (), {"returncode": 0})()

        with patch.dict(os.environ, {"FOXRUN_JEV_SCHEMA": str(_fox_root / "work/tests/fixtures/references/system-workspace-migration.sql")}), patch.object(nightly.subprocess, "run", side_effect=fake_run), patch.object(nightly, "JEV", _fox_root / "work/tests/fixtures/scripts/jev.mjs"):
            scores, cost, failure = nightly.jev_batch(self.cfg, [item], time.monotonic() + 30)
        self.assertEqual((scores, cost, failure), ({"sample": 0.12}, 0.001, None))
        self.assertFalse(storage[0].parent.exists())

    def test_first_run_uses_24_hours_and_explicit_since_can_backfill(self):
        self.cfg.now += timedelta(days=1)
        self.cfg.dry_run = True
        first = nightly.run_nightly(self.cfg, jev_fn=self.pass_jev)
        self.assertEqual((first["sessions"], first["items"]), (0, 0))
        self.assertEqual(first["since"], (self.cfg.now - timedelta(hours=24, minutes=30)).isoformat())
        self.cfg.since = datetime.fromisoformat("2026-09-29T00:00:00-04:00")
        backfill = nightly.run_nightly(self.cfg, jev_fn=self.pass_jev)
        self.assertEqual((backfill["sessions"], backfill["items"]), (1, 1))
        self.assertEqual(backfill["since"], self.cfg.since.isoformat())

    def test_new_day_rescan_of_same_item_is_idempotent(self):
        nightly.run_nightly(self.cfg, jev_fn=self.pass_jev)
        # Hide the words in the prior flag so this really rescans the same turn.
        with sqlite3.connect(self.cfg.tracker) as db:
            db.execute("UPDATE comments SET body=substr(body,1,instr(body,': ')+1) || '[redacted]' "
                       "WHERE author='session-nightly'")
        self.cfg.now += timedelta(days=1)
        self.cfg.since = datetime.fromisoformat("2026-09-29T00:00:00-04:00")
        second = nightly.run_nightly(self.cfg, jev_fn=self.pass_jev)
        self.assertEqual((second["items"], second["flagged"]), (1, 0))
        self.assertEqual(len(self.rows("SELECT id FROM runs")), 2)
        self.assertEqual(len(self.rows("SELECT id FROM comments WHERE body LIKE 'Flag:%'")), 1)

    def test_rerun_starts_second_run_same_day(self):
        nightly.run_nightly(self.cfg, jev_fn=self.pass_jev)
        self.cfg.rerun = True
        self.cfg.since = datetime.fromisoformat("2026-09-29T00:00:00-04:00")
        second = nightly.run_nightly(self.cfg, jev_fn=self.pass_jev)
        self.assertEqual((second["items"], second["flagged"]), (1, 0))
        self.assertEqual(len(self.rows("SELECT id FROM runs")), 2)

    def test_jev_unsure_and_low_score(self):
        transcript = next(self.cfg.claude_root.glob("*/*.jsonl"))
        with transcript.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"type": "user", "timestamp": "2026-09-29T01:02:00-04:00",
                                     "message": {"content": "The rule is to publish the shipping price."}}) + "\n")
        def scores(cfg, items, deadline):
            return {items[0]["key"]: 0.5, items[1]["key"]: 0.2}, 0.0, None
        result = nightly.run_nightly(self.cfg, jev_fn=scores)
        self.assertEqual((result["items"], result["flagged"]), (2, 1))
        self.assertTrue(result["candidates"][0]["unsure"])
        self.assertFalse(result["candidates"][1]["keep"])
        self.assertIn("Jev unsure", self.rows("SELECT body FROM comments WHERE body LIKE 'Flag:%'")[0][0])
        self.assertIn("drop", (self.cfg.output_root / "2026-09-29-session-check.md").read_text())

    def test_partial_jev_failure_keeps_other_scores(self):
        transcript = next(self.cfg.claude_root.glob("*/*.jsonl"))
        with transcript.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"type": "user", "timestamp": "2026-09-29T01:02:00-04:00",
                                     "message": {"content": "The rule is to publish the shipping price."}}) + "\n")
        def partial(cfg, items, deadline):
            return {items[0]["key"]: 0.2}, None, "Jev failed for 1 item(s)"
        result = nightly.run_nightly(self.cfg, jev_fn=partial)
        self.assertEqual([item["score"] for item in result["candidates"]], [0.2, None])
        self.assertEqual((result["flagged"], result["failures"]), (1, ["Jev failed for 1 item(s)"]))
        self.assertEqual(self.rows("SELECT result FROM runs"), [("fail",)])

    def test_exploratory_questions_do_not_become_candidates(self):
        self.assertFalse(nightly.actionable_turn("At what point? Is that a rule? Let's do it after we discuss."))
        self.assertFalse(nightly.actionable_turn("How many are there? Maybe we need to regroup? How?"))
        self.assertTrue(nightly.actionable_turn("What is planning? We need to now define each table in one sentence. Why?"))

    def test_question_drop_is_visible_in_evidence(self):
        transcript = next(self.cfg.claude_root.glob("*/*.jsonl"))
        with transcript.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"type": "assistant", "timestamp": "2026-09-29T01:01:30-04:00",
                                     "message": {"content": "Should we set that rule now?"}}) + "\n")
            stream.write(json.dumps({"type": "user", "timestamp": "2026-09-29T01:02:00-04:00",
                                     "message": {"content": "At what point? Is that a rule? Let's do it after we discuss."}}) + "\n")
        result = nightly.run_nightly(self.cfg, jev_fn=self.pass_jev)
        self.assertEqual(len(result["question_drops"]), 1)
        evidence = (self.cfg.output_root / "2026-09-29-session-check.md").read_text()
        self.assertIn("question-heavy turn without a concrete ruling", evidence)

    def test_warning_is_scored_like_unpromoted(self):
        with sqlite3.connect(self.cfg.tracker) as db:
            db.execute("INSERT INTO comments (subject_type,subject_id,author,at,body) "
                       "VALUES ('task','T1','agent','2026-09-29T01:02:00-04:00',?)",
                       ("person: The rule is to keep the new pricing page at twenty nine dollars.",))
        result = nightly.run_nightly(self.cfg, jev_fn=self.pass_jev)
        self.assertEqual((result["recorded"], result["items"], result["flagged"]), (1, 1, 1))
        self.assertEqual(result["candidates"][0]["kind"], "warning")

    def test_capture_after_scan_end_records_earlier_turn(self):
        with sqlite3.connect(self.cfg.tracker) as db:
            db.execute("INSERT INTO comments (subject_type,subject_id,author,at,body) "
                       "VALUES ('task','T1','agent','2026-09-29T03:45:00-04:00',?)",
                       ("person 9.29: The rule is to keep the new pricing page at twenty nine dollars.",))
        result = nightly.run_nightly(self.cfg, jev_fn=self.pass_jev)
        self.assertEqual((result["recorded"], result["candidates"][0]["kind"]), (1, "warning"))

    def test_automated_session_metadata(self):
        root = Path(self.temp.name)
        for name, metadata in (
            ("sdk", {"entrypoint": "sdk-py", "cwd": str(root)}),
            ("codex", {"type": "session_meta", "payload": {"source": "codex_exec", "cwd": str(root)}}),
            ("run", {"entrypoint": "cli", "cwd": str(nightly._fox_paths.runs() / "worker")}),
        ):
            path = root / f"{name}.jsonl"
            path.write_text(json.dumps(metadata) + "\n", encoding="utf-8")
            self.assertTrue(nightly.automated_session(path), name)

    def test_target_order_and_closed_tasks(self):
        base = datetime.fromisoformat("2026-09-29T01:00:00-04:00")
        turn = {"index": 2, "timestamp": base.isoformat(), "text": "Proceed with T8",
                "assistant_before": "T1 is done."}
        data = nightly.hc.Extract("session", "claude", person=[
            {"index": 1, "text": "T6 T6", "timestamp": base.isoformat()}, turn,
            {"index": 3, "text": "T6", "timestamp": base.isoformat()}])
        rows = [nightly.hc.prepared_row("comment", "1", "T5", "agent note",
                                            (base + timedelta(minutes=2)).isoformat(), "agent note")]
        open_tasks = {"T5", "T6", "T7", "T9"}
        self.assertEqual(nightly.task_target(turn, data, open_tasks, rows, {"T7"}), "T5")
        self.assertEqual(nightly.task_target(turn, data, open_tasks, [], {"T7"}), "T7")
        self.assertEqual(nightly.task_target(turn, data, open_tasks, [], set()), "T6")
        self.assertEqual(nightly.task_target(turn, data, {"T9"}, [], set()), "T9")

    def test_whole_turn_comment_is_recorded_without_flag(self):
        with sqlite3.connect(self.cfg.tracker) as db:
            db.execute("INSERT INTO comments (subject_type,subject_id,author,at,body) "
                       "VALUES ('task','T1','agent','2026-09-29T01:02:00-04:00',?)",
                       ("person: The rule is to keep the new pricing page at twenty nine dollars.",))
        result = nightly.run_nightly(self.cfg, jev_fn=self.pass_jev)
        self.assertEqual((result["recorded"], result["items"], result["flagged"]), (1, 1, 1))
        self.assertEqual(self.rows("SELECT count(*) FROM comments WHERE body LIKE 'Flag:%'"), [(1,)])

    def test_status_quote_like_comment_1193_does_not_record_turn(self):
        with sqlite3.connect(self.cfg.tracker) as db:
            db.execute("INSERT INTO comments (subject_type,subject_id,author,at,body) "
                       "VALUES ('task','T1','reviewer','2026-09-29T01:02:00-04:00',?)",
                       ("Opus review: the only real item is 'The rule is to keep the new pricing page at twenty nine dollars.'",))
        result = nightly.run_nightly(self.cfg, jev_fn=self.pass_jev)
        self.assertEqual((result["recorded"], result["items"]), (0, 1))

    def test_unknown_task_falls_back_to_t265(self):
        turn = {"index": 1, "timestamp": "2026-09-29T01:00:00-04:00",
                "text": "Please keep T8", "assistant_before": "T7 has no matching task."}
        data = nightly.hc.Extract("session", "claude", person=[turn])
        self.assertEqual(nightly.task_target(turn, data, {"T1", "T9"}, [], set()), "T9")

    def test_two_turns_in_one_second_get_distinct_flags(self):
        transcript = next(self.cfg.claude_root.glob("*/*.jsonl"))
        second = {"type": "user", "timestamp": "2026-09-29T01:01:00.500-04:00",
                  "message": {"content": "For T1, the rule is to show the shipping price on the page."}}
        with transcript.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(second) + "\n")
        result = nightly.run_nightly(self.cfg, jev_fn=self.pass_jev)
        self.assertEqual(result["flagged"], 2)
        self.assertEqual(len(self.rows("SELECT id FROM comments WHERE body LIKE 'Flag:%'")), 2)
        self.assertEqual(len(json.loads(self.cfg.state_file.read_text())["flagged"]), 2)

    def test_delegated_worker_brief_is_not_person_turn(self):
        path = self.cfg.codex_root / "2026/09/29/rollout-2026-09-29-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.jsonl"
        path.parent.mkdir(parents=True)
        message = "# Brief: T1 pricing\nYou are a inherit Sol worker for the Chief of Staff. The rule is to flag every decision."
        alternate = "Workspace: AgentOS\nYou are a inherit Sol worker for the Chief of Staff. The rule is to flag every decision."
        context = "Here is a list of plugins that are available but not installed. # AGENTS.md instructions for /tmp The rule is approved."
        path.write_text("\n".join(json.dumps({"type": "response_item", "timestamp": "2026-09-29T01:01:00-04:00",
                                               "payload": {"type": "message", "role": "user", "content": [
                                                   {"type": "input_text", "text": text}]}})
                                  for text in (context, message, alternate)) + "\n")
        self.cfg.dry_run = True
        result = nightly.run_nightly(self.cfg, jev_fn=self.pass_jev)
        self.assertEqual(result["sessions"], 2)
        self.assertEqual((result["settlements"], result["items"]), (1, 1))


if __name__ == "__main__":
    unittest.main()
