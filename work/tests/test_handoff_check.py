
from __future__ import annotations

import sys as _fox_sys
from pathlib import Path as _FoxPath
_fox_root = next(p for p in _FoxPath(__file__).resolve().parents if (p / 'base/core.py').is_file())
_fox_sys.path[:0] = [str(_fox_root / p) for p in ('base', 'work', 'events', 'decisions', 'memory', 'people', 'design', 'capture')]
_fox_sys.path.insert(0, str(_fox_root))
from base.tests.support import setup as _fox_test_setup
_fox_test_setup()
import io
import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import handoff_check as hc

# Placeholder replays ship with the product; recorded private replays stay local in replays/.
REPLAYS = (Path(__file__).resolve().parent / 'placeholder_replays')


class HandoffCheckTests(unittest.TestCase):
    def parse_rows(self, rows, codex=False):
        with tempfile.TemporaryDirectory() as directory:
            name = "rollout-aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa.jsonl" if codex else "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa.jsonl"
            path = Path(directory) / name
            path.write_text("\n".join(json.dumps(row) for row in rows))
            return hc.parse(path)

    def test_large_row_history_checks_only_dates_that_can_match(self):
        data = hc.Extract('session', 'claude')
        data.add_user_turn('Handle T704.', '2026-10-20T02:00:00Z')
        rows = [hc.prepared_row('comment', str(i), 'T704', 'Person: old text',
                                '2025-01-01T12:00:00-05:00', '') for i in range(5000)]
        rows.append(hc.prepared_row('comment', 'current', 'T704', 'Person: Handle T704.',
                                    '2026-10-20T03:00:00Z', ''))
        with patch.object(hc, 'row_bodies', return_value=rows), \
             patch.object(hc, 'row_matches_turn', wraps=hc.row_matches_turn) as matched:
            hc.mark_recorded(data)
        self.assertLessEqual(matched.call_count, 2)
        self.assertEqual(matched.call_args.args[1][1], 'current')

    def test_tail_reads_complete_recent_records(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa.jsonl'
            old = {"type": "user", "message": {"content": "Handle T100."}}
            new = {"type": "user", "message": {"content": "Handle T704."}}
            path.write_text(json.dumps(old) + '\n' + json.dumps(new) + '\n')
            data = hc.parse(path, tail_bytes=len(json.dumps(new)) + 4)
        self.assertEqual(data.ids, {'T704'})

    def test_system_reminder_and_system_message_ids_are_skipped(self):
        data = self.parse_rows([
            {"type": "system", "message": {"content": "T9"}},
            {"type": "user", "message": {"content": "<system-reminder>\nT106\n</system-reminder>"}},
        ])
        self.assertEqual(data.ids, set())
        self.assertEqual(data.person, [])

    def test_skill_example_and_instruction_text_are_skipped(self):
        data = self.parse_rows([
            {"type": "user", "isMeta": True, "sourceToolUseID": "skill-call",
             "message": {"content": "Base directory for this skill: /tmp/handoff\nExample: T7"}},
            {"type": "user", "message": {"content": "Base directory for this skill: /tmp/handoff\nExample: T8"}},
            {"type": "user", "message": {"content": "Use the skill for T9."}},
        ])
        self.assertEqual(data.ids, {"T9"})
        self.assertEqual(len(data.person), 1)

    def test_peer_message_is_skipped(self):
        data = self.parse_rows([
            {"type": "user", "message": {"content": '<cross-session-message sender="peer">\nT108\n</cross-session-message>'}},
        ])
        self.assertEqual(data.ids, set())
        self.assertEqual(data.person, [])

    def test_pasted_block_is_skipped(self):
        data = self.parse_rows([
            {"type": "user", "message": {"content": "<pasted_content>\nT109\n</pasted_content>"}},
        ])
        self.assertEqual(data.ids, set())
        self.assertEqual(data.person, [])

    def test_task_notification_and_local_command_are_skipped(self):
        data = self.parse_rows([
            {"type": "user", "message": {"content": "<task-notification>\n<task-id>T9</task-id>\n</task-notification>"}},
            {"type": "user", "message": {"content": "<local-command-stdout>\nT111\n</local-command-stdout>"}},
        ])
        self.assertEqual(data.ids, set())
        self.assertEqual(data.person, [])

    def test_mixed_turn_keeps_only_human_words(self):
        data = self.parse_rows([
            {"type": "user", "message": {"content": "Handle T7.\n<pasted_content>T8</pasted_content>\nThen report T9."}},
        ])
        self.assertEqual(data.ids, {"T7", "T9"})
        self.assertEqual([turn["text"] for turn in data.person], ["Handle T7. Then report T9."])

    def test_read_only_tool_text_does_not_supply_ids_or_files(self):
        data = self.parse_rows([
            {"type": "assistant", "message": {"content": "I found T5 in AGENTS.md."}},
            {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "read",
                "name": "Bash", "input": {"command": "cat docs/T6.md"}}]}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "read",
                "content": "T7 in read output"}]}},
            {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "write",
                "name": "Write", "input": {"file_path": "/tmp/T8.md", "content": "T9 example"}}]}},
        ])
        self.assertEqual(data.ids, {"T8"})
        self.assertEqual(data.files, {"/tmp/T8.md"})
        self.assertEqual(data.person, [])

    def test_codex_injected_blocks_and_read_results_are_skipped(self):
        data = self.parse_rows([
            {"type": "response_item", "payload": {"type": "message", "role": "user",
                "content": [{"type": "input_text", "text": "Do T6. <cross-session-message>T7</cross-session-message>"}]}},
            {"type": "response_item", "payload": {"type": "message", "role": "assistant",
                "content": [{"type": "output_text", "text": "T8"}]}},
            {"type": "response_item", "payload": {"type": "function_call_output", "call_id": "read",
                "output": "T9"}},
        ], codex=True)
        self.assertEqual(data.ids, {"T6"})
        self.assertEqual(len(data.person), 1)

    def test_handoff_cutoff_excludes_later_session_work(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa.jsonl"
            handoff = Path(directory) / "handoff.md"
            rows = [
                {"type": "user", "timestamp": "2026-09-24T18:00:00Z",
                 "message": {"content": "Handle T8."}},
                {"type": "assistant", "timestamp": "2026-09-24T18:01:00Z",
                 "message": {"content": [{"type": "tool_use", "name": "Write", "id": "w1",
                     "input": {"file_path": str(handoff), "content": "T8"}}]}},
                {"type": "user", "timestamp": "2026-09-25T08:00:00Z",
                 "message": {"content": "Start T9."}},
            ]
            path.write_text("\n".join(json.dumps(row) for row in rows))
            data = hc.parse(path, hc.handoff_cutoff(path, handoff))
            self.assertEqual(data.ids, {"T8"})
            self.assertEqual(len(data.person), 1)

    def test_command_ids_exclude_quoted_context(self):
        self.assertEqual(hc.command_task_ids('work comment T4 "See T7, T8, T9"'), {"T4"})
        self.assertEqual(hc.command_task_ids("sqlite3 tracker.db \"UPDATE tasks SET status='done' WHERE id='T5'\""), {"T5"})
        self.assertEqual(hc.command_task_ids('git commit -m "Finish T6"'), {"T6"})

    def test_wikilink_and_specific_glob_cover_written_file(self):
        handoff = hc._fox_paths.portfolio() / "system-workspace/handoffs/current.md"
        previous = hc._fox_paths.portfolio() / "system-workspace/handoffs/previous.md"
        output = hc._fox_paths.portfolio() / "system-workspace/outputs/2026-09-24-t230-cua-sol.md"
        self.assertTrue(hc.mentioned(str(previous), previous,
            "[[system-workspace/handoffs/previous|previous note]]", handoff))
        self.assertTrue(hc.mentioned(str(output), output,
            "Evidence: outputs/2026-09-24-t230-*.md", handoff))
        self.assertFalse(hc.mentioned(str(output), output,
            "Evidence: outputs/2026-09-24-t220-*.md", handoff))

    def test_claude_extract_and_redaction(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa.jsonl"
            rows = [
                {"type": "user", "message": {"content": "person: approved T8\nsk-secret T9"}},
                {"type": "assistant", "message": {"model": "fixture-model", "content": [
                    {"type": "tool_use", "id": "call1", "name": "Write", "input": {"file_path": "/tmp/T8.md", "content": "body"}},
                    {"type": "tool_use", "id": "call2", "name": "Bash", "input": {"command": "git commit -m T8; echo hi > /tmp/out.md\necho sk-secret > /tmp/leak.md"}},
                ]}},
                {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "call2", "content": "Exit code 0"}]}},
            ]
            path.write_text("\n".join(json.dumps(x) for x in rows))
            data = hc.parse(path)
            self.assertEqual(data.model, "fixture-model")
            self.assertIn("T8", data.ids)
            self.assertNotIn("T9", data.ids)
            self.assertEqual(data.files, {"/tmp/T8.md", "/tmp/out.md"})
            self.assertEqual(data.commands[0]["outcome"], "ok")
            self.assertEqual([x["text"] for x in data.person], ["person: approved T8"])

    def test_user_turns_recording_and_command_filter(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa.jsonl"
            rows = [
                {"type": "user", "message": {"content": "Keep the handoff grounded in the actual user instruction.\n<system-reminder>ignore</system-reminder>\ngit commit -m wrong"}},
                {"type": "user", "message": {"content": [{"type": "tool_result", "content": "fake"}]}},
                {"type": "user", "message": {"content": "Go ahead."}},
                {"type": "user", "message": {"content": "Work through this with the team."}},
            ]
            path.write_text("\n".join(json.dumps(x) for x in rows))
            data = hc.parse(path)
            data.person[0]["timestamp"] = "2026-09-24T14:00:00Z"
            self.assertEqual([x["index"] for x in data.person], [1, 2, 3])
            self.assertEqual(data.person[0]["text"], "Keep the handoff grounded in the actual user instruction.")
            self.assertEqual([x["index"] for x in data.approvals], [2])
            db = Path(directory) / "tracker.sqlite"
            with sqlite3.connect(db) as conn:
                conn.execute("CREATE TABLE comments (id INTEGER, subject_id TEXT, body TEXT, at TEXT)")
                conn.execute("INSERT INTO comments VALUES (7, 'T9', 'person: Keep the handoff grounded in the actual user instruction.', '2026-09-24T14:00:30Z')")
            hc.mark_recorded(data, (db,))
            self.assertEqual((data.person[0]["recorded"], data.person[0]["comment_id"], data.person[0]["task_id"]), (True, 7, "T9"))
            self.assertFalse(data.person[1]["recorded"])
            self.assertTrue(hc.recorded_match("Go ahead.", 'person: He said “Go ahead.”'))
            self.assertFalse(hc.recorded_match("Go ahead.", 'person: I went ahead.'))

    def test_rate_without_handoff_excludes_peer_and_pasted_turns(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa.jsonl"
            rows = [
                {"type": "assistant", "timestamp": "2026-09-24T13:59:00Z", "message": {"content": "Should I record T9?"}},
                {"type": "user", "timestamp": "2026-09-24T14:00:00Z",
                 "message": {"content": "Record this first direction."}},
                {"type": "user", "timestamp": "2026-09-24T14:01:00Z",
                 "message": {"content": '<cross-session-message sender="peer">Peer direction</cross-session-message>'}},
                {"type": "user", "timestamp": "2026-09-24T14:02:00Z",
                 "message": {"content": "<pasted_content>Pasted direction</pasted_content>"}},
                {"type": "user", "timestamp": "2026-09-24T14:03:00Z",
                 "message": {"content": "Record this second direction."}},
            ]
            path.write_text("\n".join(json.dumps(row) for row in rows))
            db = Path(directory) / "tracker.sqlite"
            with sqlite3.connect(db) as conn:
                conn.execute("CREATE TABLE comments (id INTEGER, subject_id TEXT, body TEXT, at TEXT)")
                conn.execute('INSERT INTO comments VALUES (1, \'T9\', \'person: "Record this first direction."\', \'2026-09-24T14:00:30Z\')')
            output = io.StringIO()
            with patch.object(hc, "transcript", return_value=path), patch.object(hc, "TRACKERS", (db,)), \
                 patch.object(hc, "write_extract") as write_extract, redirect_stdout(output):
                result = hc.main(["--session", "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "--rate"])
            self.assertEqual(result, 0)
            write_extract.assert_not_called()
            lines = output.getvalue().splitlines()
            self.assertEqual(lines[0], "Person record rate: 1/2 (50%)")
            self.assertRegex(lines[1], r"^U002 2026-09-24 \d\d:\d\d:\d\d [A-Z]+ \| Record this second direction\.$")
            self.assertEqual(len(lines), 2)

    def test_rate_since_uses_only_later_turns_and_repeatable_db(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa.jsonl"
            rows = [
                {"type": "user", "timestamp": "2026-09-24T14:00:00Z",
                 "message": {"content": "Old direction."}},
                {"type": "user", "timestamp": "2026-09-24T14:01:00Z",
                 "message": {"content": "Boundary direction."}},
                {"type": "assistant", "timestamp": "2026-09-24T14:01:30Z", "message": {"content": "Should I record T9?"}},
                {"type": "user", "timestamp": "2026-09-24T14:02:00Z",
                 "message": {"content": "New direction."}},
            ]
            path.write_text("\n".join(json.dumps(row) for row in rows))
            db1 = Path(directory) / "first.sqlite"
            db2 = Path(directory) / "second.sqlite"
            for db in (db1, db2):
                with sqlite3.connect(db) as conn:
                    conn.execute("CREATE TABLE comments (id INTEGER, subject_id TEXT, body TEXT, at TEXT)")
            with sqlite3.connect(db2) as conn:
                conn.execute('INSERT INTO comments VALUES (2, \'T9\', \'person: "New direction."\', \'2026-09-24T14:02:30Z\')')
            output = io.StringIO()
            with patch.object(hc, "transcript", return_value=path), redirect_stdout(output):
                result = hc.main(["--session", "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "--rate",
                                  "--since", "2026-09-24T14:01:00+00:00", "--db", str(db1), "--db", str(db2)])
            self.assertEqual(result, 0)
            self.assertEqual(output.getvalue(), "Person record rate: 1/1 (100%)\n")

    def test_codex_nested_command_and_coverage(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rollout-aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa.jsonl"
            script = 'await tools.exec_command({cmd:"git push origin T9; echo done > /tmp/T9.txt"});'
            rows = [
                {"type": "turn_context", "payload": {"model": "inherit"}},
                {"type": "response_item", "payload": {"type": "custom_tool_call", "name": "exec", "call_id": "c1", "input": script}},
                {"type": "response_item", "payload": {"type": "custom_tool_call_output", "call_id": "c1", "output": [{"type": "text", "text": "Script completed"}]}},
            ]
            path.write_text("\n".join(json.dumps(x) for x in rows))
            data = hc.parse(path)
            self.assertEqual(data.model, "inherit")
            self.assertIn("/tmp/T9.txt", data.files)
            self.assertEqual(data.commands[0]["outcome"], "ok")
            handoff = Path(directory) / "handoff.md"
            handoff.write_text("T9\n/tmp/T9.txt\n")
            result = hc.coverage(data, handoff)
            self.assertEqual(result["id_percent"], 100)
            self.assertEqual(result["file_percent"], 100)

    def test_oneshot_requires_non_null_result(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "tracker.sqlite"
            with sqlite3.connect(db) as conn:
                conn.execute("CREATE TABLE runs (session TEXT, result TEXT)")
                conn.execute("INSERT INTO runs VALUES ('abc123', NULL)")
            self.assertEqual(hc.run_result(db, "abc123"), "missing")
            with sqlite3.connect(db) as conn:
                conn.execute("UPDATE runs SET result='pass'")
            self.assertEqual(hc.run_result(db, "abc123"), "ok")

    def test_strict_coverage_uses_open_tasks_and_written_files(self):
        with tempfile.TemporaryDirectory() as directory:
            primary = Path(directory) / "primary.sqlite"
            secondary = Path(directory) / "secondary.sqlite"
            for db, rows in ((primary, [("T1", "todo"), ("T2", "done"), ("T3", "backlog")]),
                             (secondary, [("P4", "blocked"), ("WS01", "canceled")])):
                with sqlite3.connect(db) as conn:
                    conn.execute("CREATE TABLE tasks (id TEXT, status TEXT)")
                    conn.executemany("INSERT INTO tasks VALUES (?, ?)", rows)
            handoff = Path(directory) / "handoff.md"
            handoff.write_text("T1\n")
            home = Path.home()
            written = str(hc._fox_paths.portfolio() / "system-workspace/outputs/missing.md")
            present = str(hc._fox_paths.system_home() / "work/present.py")
            handoff.write_text("T1\nwork/present.py\n")
            data = hc.Extract("session", "claude", ids={"T1", "T2", "T3", "P4", "WS01", "T9",
                                                        "R-abc", "B-abc", "I-abc"},
                              files={written, present, str(hc._fox_paths.portfolio() / "system-workspace/HOME.md"),
                                     str(hc._fox_paths.portfolio() / "system-workspace/notes/other.md"),
                                     "/private/tmp/noise.md", str(handoff)})
            with patch.object(hc, "TRACKERS", (primary, secondary)):
                result = hc.coverage(data, handoff, primary)
            report = handoff.with_name("handoff.md.coverage.md").read_text()
            self.assertEqual(result["missing_ids"], ["P4"])
            self.assertEqual(result["missing_files"], [written])
            self.assertEqual((result["id_percent"], result["file_percent"]), (50, 50))
            self.assertIn("Open work missing: 1 tasks, 1 files.", report)
            self.assertIn("T2 (done)", report)
            self.assertIn("WS01 (canceled)", report)
            self.assertIn("T3\n", report)
            self.assertIn("T9\n", report)
            self.assertIn("Rows already recorded (not scored): R 1, B 1, I 1", report)
            self.assertIn("notes/other.md", report)
            self.assertNotIn("HOME.md", report)
            self.assertNotIn("/private/tmp/noise.md", report)

    def test_reads_do_not_become_written_files(self):
        data = hc.Extract("session", "claude")
        data.add_call("Read", {"file_path": "/sample/portfolio/system-workspace/docs/read.md"}, "one")
        data.add_call("Bash", {"command": "cat /sample/portfolio/system-workspace/docs/read.md"}, "two")
        self.assertEqual(data.files, set())

    def test_workspace_relative_output_is_scored(self):
        handoff = hc._fox_paths.portfolio() / "system-workspace/handoffs/lead.md"
        group, path = hc.file_group("outputs/result.md", handoff)
        self.assertEqual(group, "scored")
        self.assertEqual(path, hc._fox_paths.portfolio() / "system-workspace/outputs/result.md")
        self.assertEqual(hc.file_group("scratchpad/result.md", handoff)[0], "excluded")

    def test_settlements_reads_transcript_path_and_all_row_kinds_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture-transcript.jsonl"
            rows = [
                {"type": "user", "timestamp": "2026-09-27T20:00:00Z",
                 "message": {"content": "Before the boundary we decided to keep the old shape for now."}},
                {"type": "user", "timestamp": "2026-09-27T21:00:00Z",
                 "message": {"content": "Ruled: handoff and close are one shape with three triggers."}},
                {"type": "user", "timestamp": "2026-09-27T21:01:00Z",
                 "message": {"content": "Should we go with the nightly check?"}},
                {"type": "assistant", "timestamp": "2026-09-27T21:01:30Z",
                 "message": {"content": "Should I approve T3?"}},
                {"type": "user", "timestamp": "2026-09-27T21:02:00Z",
                 "message": {"content": "yes"}},
                {"type": "user", "timestamp": "2026-09-27T21:03:00Z",
                 "message": {"content": "From now on every seat writes its own handoff before compaction."}},
                {"type": "user", "timestamp": "2026-09-27T21:04:00Z",
                 "message": {"content": "Show me the open tasks."}},
            ]
            path.write_text("\n".join(json.dumps(row) for row in rows))
            db = Path(directory) / "tracker.sqlite"
            with sqlite3.connect(db) as conn:
                conn.execute("CREATE TABLE comments (id INTEGER, subject_id TEXT, body TEXT)")
                conn.execute("CREATE TABLE decisions (id TEXT, person_words TEXT, decided_on TEXT)")
                conn.execute("CREATE TABLE approvals (id INTEGER, subject_id TEXT, person_words TEXT, given_at TEXT)")
                conn.execute("INSERT INTO decisions VALUES ('g-cedar-shop-rule-11', "
                             "'handoff and close are one shape with three triggers', '2026-09-27T21:00:30Z')")
                conn.execute("INSERT INTO approvals VALUES (7, 'T3', '\"yes\"', '2026-09-27T21:02:30+00:00')")
            before = db.stat().st_mtime_ns
            output = io.StringIO()
            with patch.object(hc, "write_extract") as write_extract, redirect_stdout(output):
                result = hc.main(["--transcript", str(path), "--settlements", "--db", str(db),
                                  "--since", "2026-09-27T20:30:00+00:00"])
            self.assertEqual(result, 1)
            write_extract.assert_not_called()
            self.assertEqual(db.stat().st_mtime_ns, before)
            self.assertEqual(sorted(p.name for p in Path(directory).iterdir()), ["fixture-transcript.jsonl", "tracker.sqlite"])
            report = json.loads(output.getvalue())
            self.assertEqual(report["turns"], 5)
            self.assertEqual(report["settlements"], 3)
            self.assertEqual([(x["row_kind"], x["row_id"]) for x in report["promoted"]],
                             [("decision", "g-cedar-shop-rule-11"), ("approval", "7")])
            self.assertEqual([x["text"] for x in report["unpromoted"]],
                             ["From now on every seat writes its own handoff before compaction."])
            self.assertRegex(report["unpromoted"][0]["local_time"], r"^2026-09-27 \d\d:\d\d:\d\d ")

    def replay_db(self, path):
        rows = json.loads((REPLAYS / 'recorded_rows.json').read_text())
        with sqlite3.connect(path) as conn:
            conn.execute("CREATE TABLE comments (id INTEGER, subject_id TEXT, body TEXT, at TEXT)")
            conn.execute("CREATE TABLE decisions (id TEXT, person_words TEXT, decided_on TEXT, source TEXT)")
            conn.executemany("INSERT INTO comments VALUES (:id, :subject_id, :body, :at)", rows["comments"])
            conn.executemany("INSERT INTO decisions VALUES (:id, :person_words, :decided_on, :source)", rows["decisions"])

    def test_replay_9_27_lead_guard_lists_folder_rule_and_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "tracker.sqlite"
            self.replay_db(db)
            handoff = Path(directory) / "handoff.md"
            handoff.write_text("# Architect handoff\n")
            output = io.StringIO()
            with patch.object(hc, "TRACKERS", (db,)), redirect_stdout(output):
                result = hc.main(["--transcript", str(REPLAYS / 'r_9_27.jsonl'),
                                  "--handoff", str(handoff), "--kind", "lead", "--db", str(db),
                                  "--out", str(Path(directory) / "out")])
            self.assertEqual(result, 1)
            self.assertIn("unpromoted=1", output.getvalue())
            self.assertRegex(output.getvalue(), r"UNPROMOTED 2026-09-27 \d\d:27:37 ")
            self.assertIn("if it was a seboki, then the source would be from another place", output.getvalue())

    def test_replay_9_22_comments_record_lifecycle_with_separate_warning(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "tracker.sqlite"
            self.replay_db(db)
            output = io.StringIO()
            with redirect_stdout(output):
                result = hc.main(["--transcript", str(REPLAYS / 'r_9_22.jsonl'),
                                  "--settlements", "--db", str(db)])
            report = json.loads(output.getvalue())
            self.assertEqual(result, 1)
            self.assertEqual(report["settlements"], 2)
            self.assertEqual([row["row_id"] for row in report["promoted"]], ["345"])
            self.assertEqual(len(report["unpromoted"]), 1)
            self.assertEqual(len(report["warnings"]), 1)
            self.assertTrue(all(row["warning"] == "comment only, no decision row" for row in report["warnings"]))

    def test_replay_9_29_false_alarms_are_recorded_and_pace_comment_matters(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "tracker.sqlite"
            self.replay_db(db)
            data = hc.parse(REPLAYS / 'r_9_29.jsonl')
            report = hc.settlements_report(data, (db,))
            self.assertEqual(report["settlements"], 4)
            self.assertEqual([row["row_id"] for row in report["promoted"]],
                             ["pr-db-event-snapshot-verb", "g-cedar-shop-rule-4", "g-cedar-shop-rule-5", "1123"])
            self.assertEqual(report["unpromoted"], [])
            with sqlite3.connect(db) as conn:
                conn.execute("DELETE FROM decisions")
            report = hc.settlements_report(data, (db,))
            self.assertEqual([row["row_id"] for row in report["promoted"]],
                             ["1102", "1108", "1109", "1123"])
            with sqlite3.connect(db) as conn:
                conn.execute("DELETE FROM comments WHERE id=1123")
            report = hc.settlements_report(data, (db,))
            self.assertEqual([row["index"] for row in report["unpromoted"]], [4])

    def test_short_turn_requires_later_row_in_window(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "tracker.sqlite"
            with sqlite3.connect(db) as conn:
                conn.execute("CREATE TABLE comments (id INTEGER, subject_id TEXT, body TEXT, at TEXT)")
                conn.execute("INSERT INTO comments VALUES (1, 'T1', 'person (approval): yes', '2026-09-29T14:59:00-04:00')")
                conn.execute("INSERT INTO comments VALUES (2, 'T2', 'person 9.29 on item: YES!', '2026-09-29T15:01:00-04:00')")
            data = hc.Extract("fixture", "claude")
            data.assistant_text = "Should I record T2?"
            data.add_user_turn("yes", "2026-09-29T15:00:00-04:00")
            report = hc.settlements_report(data, (db,), hc.datetime.fromisoformat("2026-09-29T14:59:30-04:00"))
            self.assertEqual([row["row_id"] for row in report["promoted"]], ["2"])
            with sqlite3.connect(db) as conn:
                conn.execute("UPDATE comments SET at='2026-09-29T14:59:30-04:00' WHERE id=2")
            self.assertEqual(len(hc.settlements_report(data, (db,))["unpromoted"]), 1)

    def test_short_words_match_normalized_approval_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "tracker.sqlite"
            with sqlite3.connect(db) as conn:
                conn.execute("CREATE TABLE approvals (id INTEGER, subject_id TEXT, person_words TEXT, given_at TEXT)")
                conn.executemany("INSERT INTO approvals VALUES (?, ?, ?, ?)", [
                    (1, "T1", "  APPROVED!!! ", "2026-09-29T15:01:00-04:00"),
                    (2, "T2", "\"Go.\"", "2026-09-29T15:02:00-04:00"),
                ])
            data = hc.Extract("fixture", "claude")
            data.assistant_text = "Should I approve T1?"
            data.add_user_turn("approved", "2026-09-29T15:00:00-04:00")
            data.assistant_text = "Should I run T2?"
            data.add_user_turn("go", "2026-09-29T15:01:30-04:00")
            report = hc.settlements_report(data, (db,))
            self.assertEqual([row["row_kind"] for row in report["promoted"]], ["approval", "approval"])
            self.assertEqual(report["unpromoted"], [])

    def test_negative_matches_require_content_time_and_subject(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "tracker.sqlite"
            with sqlite3.connect(db) as conn:
                conn.execute("CREATE TABLE comments (id INTEGER, subject_id TEXT, body TEXT, at TEXT)")
                conn.execute("CREATE TABLE decisions (id TEXT, person_words TEXT, decided_on TEXT)")
                conn.executemany("INSERT INTO comments VALUES (?, ?, ?, ?)", [
                    (1, "T1", "person: Let me know if you want the old accounting report; we can review it later.",
                     "2026-09-29T13:00:00Z"),
                    (2, "T2", "person: yes", "2026-09-29T14:01:00Z"),
                ])
                conn.executemany("INSERT INTO decisions VALUES (?, ?, ?)", [
                    ("g-cedar-shop-rule-13", "yes", "2026-10-02T14:01:00Z"),
                    ("g-cedar-shop-rule-16", "we go with B for the risk level", "2026-09-29T14:03:00Z"),
                ])
            data = hc.Extract("fixture", "claude")
            data.assistant_text = "Do you want the new inventory report for T3?"
            data.add_user_turn("Let me know if the new inventory report should show stock by country and owner.",
                               "2026-09-29T14:00:00Z")
            data.assistant_text = "Should I approve T1?"
            data.add_user_turn("yes", "2026-09-29T14:00:30Z")
            data.assistant_text = "Should I record g-cedar-shop-rule-13?"
            data.add_user_turn("yes", "2026-09-29T14:01:00Z")
            data.assistant_text = "Should I settle pricing tier B?"
            data.add_user_turn("we go with B for the pricing tier", "2026-09-29T14:02:00Z")
            report = hc.settlements_report(data, (db,))
            self.assertEqual(report["promoted"], [])
            self.assertEqual([x["index"] for x in report["unpromoted"]], [2, 3, 4])
            self.assertFalse(data.person[0]["recorded"])
            hc.mark_recorded(data, (db,))
            self.assertFalse(any(x["recorded"] for x in data.person))

    def test_long_match_needs_content_or_eight_quoted_words(self):
        turn = "Please let me know if the new inventory report should show stock by country and owner."
        unrelated = "person: Please let me know if the old accounting report needs another review for finance."
        self.assertFalse(hc.recorded_match(turn, unrelated))
        self.assertTrue(hc.recorded_match(turn,
            "person (quote): 'the new inventory report should show stock by country and owner'"))

    def test_one_approval_row_holds_one_turn(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "tracker.sqlite"
            with sqlite3.connect(db) as conn:
                conn.execute("CREATE TABLE approvals (id INTEGER, subject_id TEXT, person_words TEXT, given_at TEXT)")
                conn.execute("INSERT INTO approvals VALUES (1, 'T8', 'approved', '2026-09-29T14:02:00Z')")
            data = hc.Extract("fixture", "claude")
            for minute in (0, 1):
                data.assistant_text = "Should I approve T8?"
                data.add_user_turn("approved", f"2026-09-29T14:0{minute}:00Z")
            report = hc.settlements_report(data, (db,))
            self.assertEqual([x["row_id"] for x in report["promoted"]], ["1"])
            self.assertEqual([x["index"] for x in report["unpromoted"]], [2])
            hc.mark_recorded(data, (db,))
            self.assertEqual([x["recorded"] for x in data.person], [True, False])

    def test_twenty_four_hour_window_applies_to_long_comments_and_decisions(self):
        long_text = "We decided the pricing tier should follow the annual plan for every new account."
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "tracker.sqlite"
            with sqlite3.connect(db) as conn:
                conn.execute("CREATE TABLE comments (id INTEGER, subject_id TEXT, body TEXT, at TEXT)")
                conn.execute("CREATE TABLE decisions (id TEXT, person_words TEXT, decided_on TEXT)")
                conn.execute("INSERT INTO comments VALUES (1, 'T8', ?, '2026-09-29T13:59:00Z')",
                             ("person: " + long_text,))
                conn.execute("INSERT INTO decisions VALUES ('g-cedar-shop-rule-10', ?, '2026-09-29T21:00:01Z')",
                             (long_text,))
            turn = {"text": long_text, "timestamp": "2026-09-29T14:00:00Z", "assistant_before": ""}
            initial = {row[0]: hc.row_matches_turn(turn, row) for row in hc.row_bodies((db,))}
            self.assertEqual(initial, {"comment": False, "decision": True})
            with sqlite3.connect(db) as conn:
                conn.execute("UPDATE comments SET at='2026-09-29T20:00:00Z'")
                conn.execute("UPDATE decisions SET decided_on='2026-09-29T20:00:00Z'")
            self.assertTrue(all(hc.row_matches_turn(turn, row) for row in hc.row_bodies((db,))))
            self.assertFalse(any(hc.row_matches_turn(turn, row, match_window_hours=5) for row in hc.row_bodies((db,))))

    def test_round2_real_row_runs(self):
        """Placeholder excerpts from sessions 0a0a0a01 and 0b0b0b02, with their rows."""
        cases = json.loads((REPLAYS / 'round2_real_rows.json').read_text())
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "tracker.sqlite"
            with sqlite3.connect(db) as conn:
                conn.execute("CREATE TABLE comments (id INTEGER, subject_id TEXT, body TEXT, at TEXT)")
                conn.execute("CREATE TABLE decisions (id TEXT, person_words TEXT, decided_on TEXT, source TEXT)")
                conn.execute("CREATE TABLE approvals (id INTEGER, subject_id TEXT, person_words TEXT, given_at TEXT)")
                for case in cases:
                    row = case["row"]
                    if case["kind"] == "comment":
                        conn.execute("INSERT INTO comments VALUES (:id,:subject_id,:body,:at)", row)
                    elif case["kind"] == "decision":
                        conn.execute("INSERT INTO decisions VALUES (:id,:person_words,:decided_on,:source)", row)
                    else:
                        conn.execute("INSERT INTO approvals VALUES (:id,:subject_id,:person_words,:given_at)", row)
            rows = {(row[0], row[1]): row for row in hc.row_bodies((db,))}
            for case in cases:
                key = (case["kind"], str(case["row"]["id"]))
                matched = hc.row_matches_turn(case["turn"], rows[key])
                self.assertEqual(matched, case["index"] != 1004, key)

    def test_named_settlement_replays(self):
        cases = json.loads((REPLAYS / 'settlement_cases.json').read_text())
        real = {case["index"]: case for case in json.loads((REPLAYS / 'round2_real_rows.json').read_text())}
        self.assertEqual(len(cases), 18)
        for case in cases:
            with self.subTest(case=case["name"]), tempfile.TemporaryDirectory() as directory:
                db = Path(directory) / "tracker.sqlite"
                with sqlite3.connect(db) as conn:
                    conn.execute("CREATE TABLE comments (id INTEGER, subject_id TEXT, body TEXT, at TEXT)")
                    conn.execute("CREATE TABLE decisions (id TEXT, person_words TEXT, decided_on TEXT, source TEXT)")
                    conn.execute("CREATE TABLE approvals (id INTEGER, subject_id TEXT, person_words TEXT, given_at TEXT)")
                    rows = case.get("rows", [])
                    if "real_index" in case:
                        source = real[case["real_index"]]
                        rows = [{"kind": source["kind"], **source["row"]}]
                        turns = [source["turn"]]
                    elif "real_turn" in case:
                        rows = [{"kind": case["kind"], **case["row"]}]
                        turns = [case["real_turn"]]
                    else:
                        turns = case["turns"]
                    for row in rows:
                        kind = row["kind"]
                        if kind == "comment":
                            conn.execute("INSERT INTO comments VALUES (:id,:subject_id,:body,:at)", row)
                        elif kind == "decision":
                            conn.execute("INSERT INTO decisions VALUES (:id,:person_words,:decided_on,:source)", row)
                        else:
                            conn.execute("INSERT INTO approvals VALUES (:id,:subject_id,:person_words,:given_at)", row)
                data = hc.Extract(case["name"], "claude")
                for turn in turns:
                    data.assistant_text = turn.get("assistant_before", "")
                    data.add_user_turn(turn["text"], turn["timestamp"])
                prepared = hc.row_bodies((db,))
                expected = case.get("expected_matches", [case.get("expected_match")])
                self.assertEqual([hc.row_matches_turn(turn, prepared[0]) for turn in data.person], expected)
                report = hc.settlements_report(data, (db,))
                if "expected_recorded" in case:
                    self.assertEqual([item["row_id"] for item in report["promoted"]], case["expected_recorded"])
                    self.assertEqual([item["index"] for item in report["unpromoted"]], case["expected_unpromoted"])
                    self.assertEqual([item["index"] for item in report["date_mismatch"]],
                                     case.get("expected_date_mismatch", []))
                elif hc.is_settlement(data.person[0]):
                    self.assertEqual([item["row_id"] for item in report["promoted"]], [str(rows[0]["id"])])
                else:
                    self.assertEqual(report["promoted"], [])

    def test_round3_short_approvals_use_capture_or_linked_decision(self):
        cases = json.loads((REPLAYS / 'round3_short_approvals.json').read_text())
        self.assertEqual(len(cases), 3)
        for case in cases:
            with self.subTest(case=case["name"]), tempfile.TemporaryDirectory() as directory:
                db = Path(directory) / "tracker.sqlite"
                with sqlite3.connect(db) as conn:
                    conn.execute("CREATE TABLE comments (id INTEGER, subject_id TEXT, body TEXT, at TEXT)")
                    conn.execute("CREATE TABLE decisions (id TEXT, person_words TEXT, decided_on TEXT, source TEXT)")
                    for row in case["rows"]:
                        if row["kind"] == "comment":
                            conn.execute("INSERT INTO comments VALUES (:id,:subject_id,:body,:at)", row)
                        else:
                            conn.execute("INSERT INTO decisions VALUES (:id,:person_words,:decided_on,:source)", row)
                data = hc.Extract(case["name"], "claude")
                turn = case["turn"]
                data.assistant_text = turn["assistant_before"]
                data.add_user_turn(turn["text"], turn["timestamp"])
                report = hc.settlements_report(data, (db,))
                self.assertEqual([row["row_id"] for row in report["promoted"]],
                                 [case["expected_row_id"]])
                self.assertEqual(report["unpromoted"], [])
                self.assertEqual(report["warnings"], [])

    def test_short_prompt_requires_one_capture_on_the_task(self):
        turn = {"text": "yes", "timestamp": "2026-09-29T14:00:00Z",
                "assistant_before": "Should I approve T8?"}
        capture = hc.prepared_row("comment", "1", "T8", "person 9.29: approved for this item",
                                  "2026-09-29T14:01:00Z", "person 9.29: approved for this item")
        other = hc.prepared_row("comment", "2", "T8", "person 9.29: another approval",
                                "2026-09-29T14:02:00Z", "person 9.29: another approval")
        self.assertTrue(hc.row_matches_turn(turn, capture, rows=[capture]))
        self.assertFalse(hc.row_matches_turn(turn, capture, rows=[capture, other]))

    def test_five_lost_live_matches(self):
        cases = json.loads((REPLAYS / 'nightly_live_matches.json').read_text())
        self.assertEqual(len(cases), 5)
        for case in cases:
            with self.subTest(case=case["name"]):
                row = case["row"]
                if case["kind"] == "comment":
                    prepared = hc.prepared_row("comment", str(row["id"]), row["subject_id"],
                                               row["body"], row["at"], row["body"])
                else:
                    prepared = hc.prepared_row("decision", row["id"], None,
                                               row["person_words"], row["decided_on"], row["person_words"])
                self.assertTrue(hc.row_matches_turn(case["turn"], prepared))

    def test_comment_1193_shape_is_not_a_capture(self):
        turn = {"text": "define what each table holds in one sentence",
                "timestamp": "2026-09-29T17:07:53Z", "assistant_before": "What should each table hold?"}
        comment = hc.prepared_row(
            "comment", "1193", "T5",
            "Opus review: the only real item is 'define what each table holds in one sentence' (T5).",
            "2026-09-29T20:43:52Z", "review")
        self.assertFalse(hc.row_matches_turn(turn, comment))
        for prefix in ("Re-review", "Status", "Summary"):
            with self.subTest(prefix=prefix):
                row = hc.prepared_row("comment", "1193", "T5",
                                      prefix + ": person said 'define what each table holds in one sentence'.",
                                      "2026-09-29T20:43:52Z", "review")
                self.assertFalse(hc.row_matches_turn(turn, row))
        capture = hc.prepared_row("comment", "1195", "T5",
                                  "person 9.29: define what each table holds in one sentence",
                                  "2026-09-29T21:01:58Z", "capture")
        self.assertTrue(hc.row_matches_turn(turn, capture))

    def test_date_mismatch_is_separate_from_recorded_and_unpromoted(self):
        text = "We approved the new event shape for every workspace record today."
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "tracker.sqlite"
            with sqlite3.connect(db) as conn:
                conn.execute("CREATE TABLE decisions (id TEXT, person_words TEXT, decided_on TEXT, source TEXT)")
                conn.execute("CREATE TABLE comments (id INTEGER, subject_id TEXT, body TEXT, at TEXT)")
                conn.execute("INSERT INTO decisions VALUES ('g-cedar-shop-rule-6', ?, '2026-09-28', NULL)", (text,))
                conn.execute("INSERT INTO comments VALUES (1, 'T1', ?, '2026-09-28T15:00:00Z')", ("person: " + text,))
            data = hc.Extract("drift", "claude")
            data.add_user_turn(text, "2026-09-29T14:00:00Z")
            report = hc.settlements_report(data, (db,))
            self.assertEqual(report["promoted"], [])
            self.assertEqual(report["unpromoted"], [])
            self.assertEqual(len(report["date_mismatch"]), 1)
            self.assertEqual(report["date_mismatch"][0]["timestamp"], "2026-09-29T14:00:00Z")
            self.assertIn(report["date_mismatch"][0]["row_time"],
                          ("2026-09-28", "2026-09-28T15:00:00Z"))
            self.assertEqual(report["warnings"], [])
            self.assertFalse(hc.row_matches_turn(data.person[0], hc.row_bodies((db,))[0]))
            for row in hc.row_bodies((db,)):
                self.assertIsNotNone(hc.date_mismatch_time(data.person[0], row))
            with sqlite3.connect(db) as conn:
                conn.execute("UPDATE decisions SET decided_on='2026-10-01'")
                conn.execute("UPDATE comments SET at='2026-10-01T13:00:00Z'")
            for row in hc.row_bodies((db,)):
                self.assertIsNotNone(hc.date_mismatch_time(data.person[0], row))
            with sqlite3.connect(db) as conn:
                conn.execute("UPDATE decisions SET decided_on='2026-09-27'")
                conn.execute("UPDATE comments SET at='2026-09-27T15:00:00Z'")
            report = hc.settlements_report(data, (db,))
            self.assertEqual(report["date_mismatch"], [])
            self.assertEqual(len(report["unpromoted"]), 1)

    def test_p9_date_mismatch_fails_lead_handoff(self):
        case = next(case for case in json.loads((REPLAYS / 'settlement_cases.json').read_text())
                    if case["name"].startswith("P9-"))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db = root / "tracker.sqlite"
            with sqlite3.connect(db) as conn:
                conn.execute("CREATE TABLE comments (id INTEGER, subject_id TEXT, body TEXT, at TEXT)")
                conn.execute("INSERT INTO comments VALUES (:id,:subject_id,:body,:at)", case["rows"][0])
            handoff = root / "2026-09-29-001-current.md"
            handoff.write_text("---\ntype: handoff\n---\n")
            transcript = root / "fixture.jsonl"
            transcript.write_text("\n".join(json.dumps(row) for row in [
                {"type": "user", "timestamp": case["turns"][0]["timestamp"],
                 "message": {"content": case["turns"][0]["text"]}},
                {"type": "assistant", "timestamp": "2026-09-29T14:01:00Z",
                 "message": {"content": [{"type": "tool_use", "name": "Write",
                                          "input": {"file_path": str(handoff)}}]}},
            ]) + "\n")
            output = io.StringIO()
            with redirect_stdout(output):
                result = hc.main(["--transcript", str(transcript), "--handoff", str(handoff),
                                  "--kind", "lead", "--db", str(db), "--out", str(root / "out")])
            self.assertEqual(result, 1)
            self.assertIn("date_mismatch=1", output.getvalue())
            self.assertIn("DATE MISMATCH", output.getvalue())

    def test_unconditional_cues_and_question_bound_cues(self):
        for cue in ("approved", "yes", "run it", "send it"):
            turn = {"text": cue, "assistant_before": "", "approval": False}
            self.assertTrue(hc.is_settlement(turn), cue)
            turn["text"] = f"We discussed the item at length, and {cue} before moving ahead."
            self.assertTrue(hc.is_settlement(turn), cue)
        for cue in ("decision", "decide", "final", "rule", "I agree", "sounds good"):
            turn = {"text": f"Here is a long turn about the {cue} we discussed yesterday.",
                    "assistant_before": "", "approval": False}
            self.assertFalse(hc.is_settlement(turn), cue)
            turn["assistant_before"] = "Should I record this?"
            self.assertTrue(hc.is_settlement(turn), cue)

    def test_p5_short_approval_cannot_cross_r_number(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "tracker.sqlite"
            with sqlite3.connect(db) as conn:
                conn.execute("CREATE TABLE comments (id INTEGER, subject_id TEXT, body TEXT, at TEXT)")
                conn.execute("INSERT INTO comments VALUES (1, 'T5', \"person on R15: 'approved'\", '2026-09-29T14:15:00-04:00')")
            turn = {"text": "approved", "timestamp": "2026-09-29T14:00:00-04:00",
                    "assistant_before": "Should I approve T5 R14?"}
            self.assertFalse(hc.row_matches_turn(turn, hc.row_bodies((db,))[0]))

    def test_p6_unrelated_backfill_cannot_hold_long_turn(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "tracker.sqlite"
            with sqlite3.connect(db) as conn:
                conn.execute("CREATE TABLE comments (id INTEGER, subject_id TEXT, body TEXT, at TEXT)")
                conn.execute("INSERT INTO comments VALUES (1, 'T6', "
                             "'Backfill is final; run the migration tonight after review.', "
                             "'2026-09-29T16:00:00-04:00')")
            turn = {"text": "Okay sounds good, run the migration tonight, that is final.",
                    "timestamp": "2026-09-29T14:00:00-04:00", "assistant_before": "Migration details follow.",
                    "approval": False}
            self.assertFalse(hc.is_settlement(turn))
            self.assertFalse(hc.row_matches_turn(turn, hc.row_bodies((db,))[0]))
            turn["assistant_before"] = "Should I run the migration tonight?"
            self.assertTrue(hc.is_settlement(turn))
            self.assertFalse(hc.row_matches_turn(turn, hc.row_bodies((db,))[0]))

    def test_local_comment_time_and_next_day_decision(self):
        text = "We go with the same event shape for every workspace record."
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "tracker.sqlite"
            with sqlite3.connect(db) as conn:
                conn.execute("CREATE TABLE comments (id INTEGER, subject_id TEXT, body TEXT, at TEXT)")
                conn.execute("CREATE TABLE decisions (id TEXT, person_words TEXT, decided_on TEXT, source TEXT)")
                conn.execute("INSERT INTO comments VALUES (1, 'T1', ?, '2026-09-29T20:05:00')",
                             ("person: Recorded from call: " + text,))
                conn.execute("INSERT INTO decisions VALUES ('g-cedar-shop-rule-10', ?, '2026-09-30', NULL)", (text,))
            turn = {"text": text, "timestamp": "2026-09-30T00:00:00Z", "assistant_before": ""}
            self.assertTrue(all(hc.row_matches_turn(turn, row) for row in hc.row_bodies((db,))))

    def test_six_word_turn_requires_all_six_in_order(self):
        turn = "We approve the new status list today."
        self.assertTrue(hc.recorded_match(turn, "Recorded: We approve the new status list today.", "decision"))
        self.assertFalse(hc.recorded_match(turn, "Recorded: We approve the status list today.", "decision"))

    def test_long_run_cannot_repeat_preceding_assistant_words(self):
        proposal = "Every skill writes its own receipt to the shared log at the end of each run."
        turn = {"text": "The rule is to reject this proposal. " + proposal,
                "timestamp": "2026-09-29T14:00:00Z", "assistant_before": proposal}
        row = hc.prepared_row("decision", "g-cedar-shop-rule-15", None, proposal, "2026-09-29", proposal) + (False,)
        self.assertFalse(hc.row_matches_turn(turn, row))

    def test_resume_repeat_is_one_turn(self):
        data = self.parse_rows([
            {"type": "user", "timestamp": "2026-09-29T14:00:00Z", "message": {"content": "approved"}},
            {"type": "user", "timestamp": "2026-09-29T14:00:00Z", "message": {"content": "different turn"}},
            {"type": "user", "timestamp": "2026-09-29T14:00:00Z", "message": {"content": "approved"}},
            {"type": "user", "timestamp": "2026-09-29T14:00:01Z", "message": {"content": "approved"}},
            {"type": "user", "timestamp": "2026-09-29T14:00:04Z", "message": {"content": "approved"}},
        ])
        self.assertEqual([x["text"] for x in data.person], ["approved", "different turn", "approved"])

    def test_pure_ack_needs_direct_question(self):
        data = hc.Extract("fixture", "claude")
        data.add_user_turn("Alright sounds good. I'm waiting.", "2026-09-29T14:00:00Z")
        self.assertFalse(hc.is_settlement(data.person[0]))
        data.assistant_text = "Want me to wait?"
        data.add_user_turn("Alright sounds good. I'm waiting.", "2026-09-29T14:01:00Z")
        self.assertTrue(hc.is_settlement(data.person[1]))

    def test_previous_handoff_requires_name_and_frontmatter(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "2026-09-29-003-current.md"
            target.write_text("---\ntype: handoff\n---\n")
            good = root / "2026-09-29-001-good.md"
            good.write_text("---\ntype: handoff\n---\n")
            bad_name = root / "latest.md"
            bad_name.write_text("---\ntype: handoff\n---\n")
            bad_type = root / "2026-09-29-002-note.md"
            bad_type.write_text("---\ntype: note\n---\n")
            rows = [{"type": "assistant", "timestamp": f"2026-09-29T14:0{i}:00Z",
                     "message": {"content": [{"type": "tool_use", "name": "Write",
                                              "input": {"file_path": str(path)}}]}}
                    for i, path in enumerate((good, bad_name, bad_type, target), 1)]
            transcript = root / "fixture.jsonl"
            transcript.write_text("\n".join(json.dumps(row) for row in rows))
            latest, previous = hc.handoff_window(transcript, target)
            self.assertEqual(latest.isoformat(), "2026-09-29T14:04:00+00:00")
            self.assertEqual(previous.isoformat(), "2026-09-29T14:01:00+00:00")

    def test_lead_row_after_handoff_needs_handoff_rewrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db = root / "tracker.sqlite"
            with sqlite3.connect(db) as conn:
                conn.execute("CREATE TABLE approvals (id INTEGER, subject_id TEXT, person_words TEXT, given_at TEXT)")
                conn.execute("INSERT INTO approvals VALUES (1, 'T8', 'approved', '2026-09-29T14:04:00Z')")
            handoff = root / "2026-09-29-001-current.md"
            handoff.write_text("---\ntype: handoff\n---\n")
            rows = [
                {"type": "assistant", "timestamp": "2026-09-29T14:00:00Z",
                 "message": {"content": "Should I approve T8?"}},
                {"type": "user", "timestamp": "2026-09-29T14:01:00Z",
                 "message": {"content": "approved"}},
                {"type": "assistant", "timestamp": "2026-09-29T14:03:00Z",
                 "message": {"content": [{"type": "tool_use", "name": "Write",
                                          "input": {"file_path": str(handoff)}}]}},
            ]
            transcript = root / "fixture.jsonl"
            transcript.write_text("\n".join(json.dumps(row) for row in rows))
            args = ["--transcript", str(transcript), "--handoff", str(handoff),
                    "--kind", "lead", "--db", str(db), "--out", str(root / "out")]
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(hc.main(args), 1)
            self.assertIn("Rows written after this handoff cannot clear a failure", output.getvalue())
            rows.append({"type": "assistant", "timestamp": "2026-09-29T14:05:00Z",
                         "message": {"content": [{"type": "tool_use", "name": "Edit",
                                                  "input": {"file_path": str(handoff)}}]}})
            transcript.write_text("\n".join(json.dumps(row) for row in rows))
            with redirect_stdout(io.StringIO()):
                self.assertEqual(hc.main(args), 0)

    def test_lead_window_starts_after_previous_handoff(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db = root / "tracker.sqlite"
            with sqlite3.connect(db) as conn:
                conn.execute("CREATE TABLE comments (id INTEGER, subject_id TEXT, body TEXT, at TEXT)")
            previous, handoff = root / "2026-09-29-001-previous.md", root / "2026-09-29-002-current.md"
            previous.write_text("---\ntype: handoff\n---\n")
            handoff.write_text("# Current\n")
            rows = [
                {"type": "user", "timestamp": "2026-09-29T14:00:00Z", "message": {"content": "yes"}},
                {"type": "assistant", "timestamp": "2026-09-29T14:01:00Z", "message": {"content": [
                    {"type": "tool_use", "name": "Write", "input": {"file_path": str(previous)}}]}},
                {"type": "user", "timestamp": "2026-09-29T14:02:00Z", "message": {"content": "approved"}},
                {"type": "assistant", "timestamp": "2026-09-29T14:03:00Z", "message": {"content": [
                    {"type": "tool_use", "name": "Write", "input": {"file_path": str(handoff)}}]}},
            ]
            transcript = root / "fixture.jsonl"
            transcript.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            output = io.StringIO()
            with patch.object(hc, "TRACKERS", (db,)), redirect_stdout(output):
                result = hc.main(["--transcript", str(transcript), "--handoff", str(handoff),
                                  "--kind", "lead", "--db", str(db), "--out", str(root / "out")])
            self.assertEqual(result, 1)
            self.assertIn("settlements=1", output.getvalue())
            self.assertIn("| approved", output.getvalue())
            self.assertNotIn("| yes", output.getvalue())

    def test_settlements_missing_transcript_exits_nonzero(self):
        output = io.StringIO()
        with patch("sys.stderr", output):
            result = hc.main(["--transcript", "/nonexistent/t.jsonl", "--settlements"])
        self.assertEqual(result, 1)
        self.assertIn("transcript not found", output.getvalue())


if __name__ == "__main__":
    unittest.main()
