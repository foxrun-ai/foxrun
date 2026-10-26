"""handoff-boot prints the seat's boot sequence and never blocks a session start."""

import json
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "bin" / "handoff-boot"
SESSION = "11111111-2222-3333-4444-555555555555"


def note(session="other", tags=None, seat=None, body="body", timestamp=None):
    lines = ["---", "type: handoff", "workspace: foxrun-dev", f"session: {session}"]
    if timestamp:
        lines.append(f"timestamp: {timestamp}")
    if seat:
        lines.append(f"seat: {seat}")
    if tags is not None:
        lines.append(f"tags: [{', '.join(tags)}]")
    return "\n".join(lines + ["---", "", body, ""])


class HandoffBootTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.vault = Path(self.folder.name) / "vault"
        self.handoffs = self.vault / "foxrun-dev" / "history" / "handoffs"
        self.handoffs.mkdir(parents=True)
        self.cwd = self.vault / "foxrun-dev"

    def tearDown(self):
        self.folder.cleanup()

    def write(self, name, text):
        (self.handoffs / name).write_text(text, encoding="utf-8")

    def isolated_env(self):
        """The process env without FOXRUN_SEAT, with the nightly plist and tracker in the temp folder."""
        environment = {key: value for key, value in os.environ.items() if key != "FOXRUN_SEAT"}
        environment["FOXRUN_NIGHTLY_PLIST"] = str(Path(self.folder.name) / "nightly.plist")
        environment["FOXRUN_TRACKER"] = str(self.cwd / "data.db")
        return environment

    def run_boot(self, *args, stdin="", env=None):
        environment = self.isolated_env()
        environment.update(env or {})
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--vault", str(self.vault), *args],
            input=stdin, capture_output=True, text=True, env=environment, check=False,
        )

    def picked(self, *args, stdin="", env=None):
        result = self.run_boot(*args, "--json", stdin=stdin, env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        picked = json.loads(result.stdout)["picked"]
        return Path(picked).name if picked else None

    def test_seat_by_flag(self):
        self.write("2026-09-26-001-chief-of-staff-night.md", note())
        self.write("2026-09-26-002-architect-boot.md", note())
        self.assertEqual(self.picked("--seat", "architect", "--cwd", str(self.cwd)), "2026-09-26-002-architect-boot.md")

    def test_seat_by_env(self):
        self.write("2026-09-26-001-chief-of-staff-night.md", note())
        self.write("2026-09-26-002-architect-boot.md", note())
        self.assertEqual(
            self.picked("--cwd", str(self.cwd), env={"FOXRUN_SEAT": "chief-of-staff"}),
            "2026-09-26-001-chief-of-staff-night.md",
        )

    def test_flag_beats_env(self):
        self.write("2026-09-26-001-chief-of-staff-night.md", note())
        self.write("2026-09-26-002-architect-boot.md", note())
        self.assertEqual(
            self.picked("--seat", "architect", "--cwd", str(self.cwd), env={"FOXRUN_SEAT": "chief-of-staff"}),
            "2026-09-26-002-architect-boot.md",
        )

    def test_seat_by_session_match_then_newest_for_that_seat(self):
        self.write("2026-09-25-001-lead-note.md", note(session=SESSION, tags=["chief-of-staff", "handoff"]))
        self.write("2026-09-26-001-chief-of-staff-boot.md", note())
        self.write("2026-09-26-002-architect-boot.md", note(session=SESSION + "x"))
        hook = json.dumps({"session_id": SESSION, "cwd": str(self.cwd), "source": "compact"})
        self.assertEqual(self.picked(stdin=hook), "2026-09-26-001-chief-of-staff-boot.md")

    def test_tags_match_when_name_does_not(self):
        self.write("2026-09-26-001-night-notes.md", note(tags=["architect", "boot"]))
        self.write("2026-09-26-002-other-notes.md", note(tags=["chief-of-staff"]))
        self.assertEqual(self.picked("--seat", "architect", "--cwd", str(self.cwd)), "2026-09-26-001-night-notes.md")

    def test_file_name_subject_matches(self):
        self.write("2026-09-26-004-chief-of-staff-handoff.md", note())
        self.assertEqual(
            self.picked("--seat", "chief-of-staff", "--cwd", str(self.cwd)), "2026-09-26-004-chief-of-staff-handoff.md"
        )

    def test_explicit_seat_field_wins_over_name(self):
        self.write("2026-09-26-001-architect-boot.md", note())
        self.write("2026-09-26-002-architect-for-cos.md", note(seat="chief-of-staff"))
        self.assertEqual(self.picked("--seat", "architect", "--cwd", str(self.cwd)), "2026-09-26-001-architect-boot.md")
        self.assertEqual(self.picked("--seat", "chief-of-staff", "--cwd", str(self.cwd)), "2026-09-26-002-architect-for-cos.md")

    def test_newest_is_date_then_number_and_coverage_files_are_ignored(self):
        self.write("2026-09-25-009-architect-a.md", note())
        self.write("2026-09-26-002-architect-b.md", note())
        self.write("2026-09-26-010-architect-c.md", note())
        self.write("2026-09-26-011-architect-d.md.coverage.md", note())
        self.assertEqual(self.picked("--seat", "architect", "--cwd", str(self.cwd)), "2026-09-26-010-architect-c.md")

    def boot_context(self, *args):
        result = self.run_boot("--seat", "architect", "--cwd", str(self.cwd), *args)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]

    def boot_report(self):
        result = self.run_boot("--seat", "architect", "--cwd", str(self.cwd), "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_sequence_handwritten_then_newer_notes_oldest_first(self):
        lead = "2026-09-29-001-architect-lead.md"
        first = "2026-09-29-002-architect-precompact.md"
        second = "2026-09-29-003-architect-precompact.md"
        self.write(lead, note(session=SESSION, seat="architect", body="lead details"))
        self.write(first, note(session=SESSION, seat="architect", tags=["precompact"], body="first note"))
        self.write(second, note(session=SESSION, seat="architect", tags=["precompact"], body="second note"))
        report = self.boot_report()
        self.assertEqual(Path(report["picked"]).name, lead)
        self.assertEqual([Path(path).name for path in report["sequence"]], [lead, first, second])
        self.assertEqual(report["cut"], [])
        context = self.boot_context()
        self.assertTrue(context.startswith("Boot: read these handoffs in order; rows win over them."))
        self.assertIn(f"File 1 of 3: {self.handoffs / lead}", context)
        self.assertIn(f"File 2 of 3: {self.handoffs / first}", context)
        self.assertIn(f"File 3 of 3: {self.handoffs / second}", context)
        self.assertLess(context.index("lead details"), context.index("first note"))
        self.assertLess(context.index("first note"), context.index("second note"))

    def test_clean_note_without_unpromoted_still_joins_the_sequence(self):
        lead = "2026-09-29-001-architect-lead.md"
        thin = "2026-09-29-002-architect-precompact.md"
        self.write(lead, note(session=SESSION, seat="architect", body="lead details"))
        self.write(thin, note(session=SESSION, seat="architect", tags=["precompact"], body="thin note"))
        report = self.boot_report()
        self.assertEqual([Path(path).name for path in report["sequence"]], [lead, thin])
        self.assertNotIn("also_read", report)

    def test_no_handwritten_prints_notes_oldest_first(self):
        first = "2026-09-29-001-architect-precompact.md"
        second = "2026-09-29-002-architect-precompact.md"
        self.write(first, note(session=SESSION, seat="architect", tags=["precompact"], body="first note"))
        self.write(second, note(session=SESSION, seat="architect", tags=["precompact"], body="second note"))
        report = self.boot_report()
        self.assertEqual([Path(path).name for path in report["sequence"]], [first, second])
        self.assertIn("no hand-written handoff", report["reason"])
        context = self.boot_context()
        self.assertIn(f"File 1 of 2: {self.handoffs / first}", context)
        self.assertIn(f"File 2 of 2: {self.handoffs / second}", context)
        self.assertLess(context.index("first note"), context.index("second note"))

    def test_cap_keeps_handwritten_whole_and_cuts_oldest_notes_first(self):
        lead = "2026-09-29-001-architect-lead.md"
        oldest = "2026-09-29-002-architect-precompact.md"
        middle = "2026-09-29-003-architect-precompact.md"
        newest = "2026-09-29-004-architect-precompact.md"
        self.write(lead, note(session=SESSION, seat="architect", body="LEAD" + "l" * 7000 + "LEADEND"))
        self.write(oldest, note(session=SESSION, seat="architect", tags=["precompact"], body="OLDEST" + "o" * 3000))
        self.write(middle, note(session=SESSION, seat="architect", tags=["precompact"], body="MIDDLE" + "m" * 3000))
        self.write(newest, note(session=SESSION, seat="architect", tags=["precompact"], body="NEWEST" + "n" * 3000))
        report = self.boot_report()
        self.assertEqual([Path(path).name for path in report["cut"]], [oldest])
        self.assertEqual([Path(path).name for path in report["shortened"]], [middle])
        context = self.boot_context()
        self.assertIn("LEADEND", context)
        self.assertNotIn("OLDEST", context)
        self.assertIn("Cut for length: 1 older pre-compaction note(s), not printed.", context)
        self.assertIn(str(self.handoffs / oldest), context)
        self.assertIn("MIDDLE", context)
        self.assertIn("[cut at", context)
        self.assertIn("NEWEST" + "n" * 3000, context)
        self.assertLess(context.index("LEADEND"), context.index("MIDDLE"))
        self.assertLess(context.index("MIDDLE"), context.index("NEWEST"))
        self.assertLess(len(context), 12500)

    def test_older_precompact_unpromoted_does_not_join_newer_lead(self):
        thin = "2026-09-29-001-architect-precompact.md"
        lead = "2026-09-29-002-architect-lead.md"
        self.write(thin, note(session=SESSION, seat="architect", tags=["precompact"],
                              body="## Unpromoted\n\n- old item"))
        self.write(lead, note(session=SESSION, seat="architect", body="lead details"))
        report = self.boot_report()
        self.assertEqual(Path(report["picked"]).name, lead)
        self.assertEqual([Path(path).name for path in report["sequence"]], [lead])

    def test_two_seats_in_one_workspace(self):
        self.write("2026-09-26-001-chief-of-staff-night.md", note(tags=["chief-of-staff"]))
        self.write("2026-09-26-002-architect-boot.md", note(tags=["architect"]))
        self.write("2026-09-26-003-chief-of-staff-boot.md", note(tags=["chief-of-staff"]))
        self.assertEqual(self.picked("--seat", "architect", "--cwd", str(self.cwd)), "2026-09-26-002-architect-boot.md")
        self.assertEqual(self.picked("--seat", "chief-of-staff", "--cwd", str(self.cwd)), "2026-09-26-003-chief-of-staff-boot.md")

    def test_zero_matches_prints_nothing(self):
        self.write("2026-09-26-001-architect-boot.md", note())
        result = self.run_boot("--seat", "nobody", "--cwd", str(self.cwd))
        self.assertEqual((result.returncode, result.stdout), (0, ""))

    def test_no_seat_prints_nothing(self):
        self.write("2026-09-26-001-architect-boot.md", note())
        hook = json.dumps({"session_id": "unknown", "cwd": str(self.cwd), "source": "startup"})
        result = self.run_boot(stdin=hook)
        self.assertEqual((result.returncode, result.stdout), (0, ""))

    def test_cwd_outside_vault_prints_nothing(self):
        self.write("2026-09-26-001-architect-boot.md", note())
        outside = Path(self.folder.name) / "elsewhere"
        outside.mkdir()
        result = self.run_boot("--seat", "architect", "--cwd", str(outside))
        self.assertEqual((result.returncode, result.stdout), (0, ""))

    def test_vault_root_with_no_seat_prints_nothing(self):
        self.write("2026-09-26-001-architect-boot.md", note())
        hook = json.dumps({"session_id": "unknown", "cwd": str(self.vault), "source": "startup"})
        result = self.run_boot(stdin=hook)
        self.assertEqual((result.returncode, result.stdout), (0, ""))

    def test_bad_stdin_exits_zero_silent(self):
        self.write("2026-09-26-001-architect-boot.md", note())
        for stdin in ("{not json", "[1, 2]", "\x00\x01"):
            result = self.run_boot("--seat", "architect", "--cwd", str(self.cwd), stdin=stdin)
            self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))

    def test_bad_flag_exits_zero(self):
        result = self.run_boot("--no-such-flag")
        self.assertEqual((result.returncode, result.stdout), (0, ""))

    def test_no_nightly_flag_keeps_handoff_without_status_scan(self):
        self.write("2026-09-26-001-architect-boot.md", note())
        plist = self.vault / "nightly.plist"
        plist.write_text("present")
        env = {"FOXRUN_TRACKER": str(self.vault / "missing.db"),
               "FOXRUN_NIGHTLY_PLIST": str(plist)}
        ordinary = self.run_boot("--seat", "architect", "--cwd", str(self.cwd), env=env)
        fast = self.run_boot("--seat", "architect", "--cwd", str(self.cwd), "--no-nightly", env=env)
        self.assertIn("Nightly check has never run", ordinary.stdout)
        self.assertIn("2026-09-26-001-architect-boot.md", fast.stdout)
        self.assertNotIn("Nightly check", fast.stdout)

    def test_no_stdin_uses_flags(self):
        self.write("2026-09-26-001-architect-boot.md", note())
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--vault", str(self.vault), "--seat", "architect", "--cwd", str(self.cwd)],
            stdin=subprocess.DEVNULL, capture_output=True, text=True, env=self.isolated_env(), check=False,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("2026-09-26-001-architect-boot.md", result.stdout)

    def test_open_empty_stdin_does_not_hang(self):
        # An agent shell leaves stdin open and never writes; the seat wake call must still return.
        self.write("2026-09-26-001-architect-boot.md", note())
        environment = self.isolated_env()
        process = subprocess.Popen(
            [sys.executable, str(SCRIPT), "--vault", str(self.vault), "--json", "--seat", "architect", "--cwd", str(self.cwd)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=environment,
        )
        try:
            # wait(), not communicate(): communicate closes stdin, which would hide the bug.
            process.wait(timeout=2)
            stdout, stderr = process.stdout.read(), process.stderr.read()
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            self.fail("handoff-boot blocked on an open, empty stdin")
        finally:
            process.stdin.close()
            process.stdout.close()
            process.stderr.close()
        self.assertEqual(process.returncode, 0, stderr)
        self.assertEqual(Path(json.loads(stdout)["picked"]).name, "2026-09-26-001-architect-boot.md")

    def test_no_flags_waits_for_slow_hook_json(self):
        # The hook case (no --seat, no --cwd) blocks to EOF, so a slow writer never loses the JSON.
        self.write("2026-09-26-001-architect-boot.md", note(session=SESSION, seat="architect"))
        environment = self.isolated_env()
        process = subprocess.Popen(
            [sys.executable, str(SCRIPT), "--vault", str(self.vault), "--json"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=environment,
        )
        time.sleep(0.5)
        hook = json.dumps({"session_id": SESSION, "cwd": str(self.cwd), "source": "startup"})
        stdout, stderr = process.communicate(hook, timeout=10)
        self.assertEqual(process.returncode, 0, stderr)
        report = json.loads(stdout)
        self.assertEqual(report["session"], SESSION)
        self.assertEqual(Path(report["picked"]).name, "2026-09-26-001-architect-boot.md")

    def test_piped_json_still_read_and_flags_win(self):
        self.write("2026-09-26-001-architect-boot.md", note(session=SESSION, seat="architect"))
        self.write("2026-09-26-002-chief-of-staff-night.md", note())
        hook = json.dumps({"session_id": SESSION, "cwd": str(self.cwd), "source": "startup"})
        self.assertEqual(self.picked(stdin=hook), "2026-09-26-001-architect-boot.md")
        self.assertEqual(self.picked("--seat", "chief-of-staff", stdin=hook), "2026-09-26-002-chief-of-staff-night.md")

    def test_hook_output_shape(self):
        self.write("2026-09-26-001-architect-boot.md", note(body="hello architect"))
        hook = json.dumps({"session_id": "s", "cwd": str(self.cwd), "source": "startup", "hook_event_name": "SessionStart"})
        result = self.run_boot("--seat", "architect", stdin=hook)
        payload = json.loads(result.stdout)
        output = payload["hookSpecificOutput"]
        self.assertEqual(output["hookEventName"], "SessionStart")
        context = output["additionalContext"]
        self.assertTrue(context.startswith("Boot: read this handoff first; rows win over it."))
        self.assertIn(str(self.handoffs / "2026-09-26-001-architect-boot.md"), context)
        self.assertIn("hello architect", context)

    def test_superseded_decisions_since_handoff(self):
        self.write("2026-09-26-001-architect-boot.md", note(
            timestamp="2026-09-26T10:00:00-04:00", body="prior work"))
        database = self.cwd / "data.db"
        with sqlite3.connect(database) as db:
            db.executescript("CREATE TABLE decisions(id TEXT PRIMARY KEY,status TEXT);"
                             "CREATE TABLE activity(subject_type TEXT,subject_id TEXT,field TEXT,"
                             "new_value TEXT,at TEXT);")
            db.executemany("INSERT INTO decisions VALUES (?,?)", [
                ("g-new", "superseded"), ("g-old", "superseded"),
                ("g-still", "ruled"), ("g-no-event", "superseded"),
            ])
            db.executemany("INSERT INTO activity VALUES (?,?,?,?,?)", [
                ("decision", "g-new", "status", "superseded", "2026-09-26T11:00:00-04:00"),
                ("decision", "g-new", "status", "superseded", "2026-09-26T12:00:00-04:00"),
                ("decision", "g-old", "status", "superseded", "2026-09-26T09:00:00-04:00"),
                ("decision", "g-still", "status", "superseded", "2026-09-26T11:00:00-04:00"),
            ])
        database.chmod(0o444)
        result = self.run_boot("--seat", "architect", "--cwd", str(self.cwd))
        self.assertEqual(0, result.returncode)
        context = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Superseded since your last handoff: g-new", context)
        self.assertNotIn("g-old", context)
        self.assertNotIn("g-still", context)

    def test_no_superseded_line_when_none(self):
        self.write("2026-09-26-001-architect-boot.md", note(timestamp="2026-09-26T10:00:00-04:00"))
        result = self.run_boot("--seat", "architect", "--cwd", str(self.cwd))
        context = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertNotIn("Superseded since your last handoff", context)

    def test_output_cap(self):
        self.write("2026-09-26-001-architect-boot.md", note(body="x" * 20000))
        result = self.run_boot("--seat", "architect", "--cwd", str(self.cwd))
        context = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("[cut at 12000 of", context)
        self.assertLess(len(context), 12400)

    def test_dry_run_prints_no_hook_output(self):
        self.write("2026-09-26-001-architect-boot.md", note())
        result = self.run_boot("--dry-run", "--seat", "architect", "--cwd", str(self.cwd))
        self.assertEqual((result.returncode, result.stdout), (0, ""))
        self.assertIn("2026-09-26-001-architect-boot.md", result.stderr)

    def test_workspace_flag(self):
        self.write("2026-09-26-001-architect-boot.md", note())
        result = self.run_boot("--json", "--seat", "architect", "--workspace", "foxrun-dev", "--cwd", "/")
        self.assertEqual(Path(json.loads(result.stdout)["picked"]).name, "2026-09-26-001-architect-boot.md")

    def nightly_db(self, ended=None, result="pass"):
        database = self.cwd / "data.db"
        with sqlite3.connect(database) as db:
            db.executescript(
                'CREATE TABLE runs(subject_type TEXT,subject_id TEXT,"by" TEXT,ended_at TEXT,result TEXT);'
                'CREATE TABLE comments(id INTEGER,subject_type TEXT,subject_id TEXT,author TEXT,at TEXT,body TEXT);'
            )
            if ended:
                db.execute("INSERT INTO runs VALUES ('task','dream-review','session-nightly',?,?)", (ended, result))
        return database

    def install_plist(self):
        plist = Path(self.folder.name) / "nightly.plist"
        plist.write_text("installed", encoding="utf-8")
        return plist

    def test_nightly_never_run_only_after_plist_exists(self):
        self.write("2026-09-26-001-architect-boot.md", note())
        self.nightly_db()
        self.assertNotIn("Nightly check", json.loads(self.run_boot(
            "--seat", "architect", "--cwd", str(self.cwd)).stdout)
            ["hookSpecificOutput"]["additionalContext"])
        self.install_plist()
        context = json.loads(self.run_boot("--seat", "architect", "--cwd", str(self.cwd)).stdout)
        self.assertIn("Nightly check has never run", context["hookSpecificOutput"]["additionalContext"])

    def test_tracker_override_is_read(self):
        self.write("2026-09-26-001-architect-boot.md", note())
        self.install_plist()
        tracker = Path(self.folder.name) / "elsewhere.sqlite"
        with sqlite3.connect(tracker) as db:
            db.execute('CREATE TABLE runs(subject_type TEXT,subject_id TEXT,"by" TEXT,ended_at TEXT,result TEXT)')
            db.execute("INSERT INTO runs VALUES ('task','any-task','session-nightly',?,'pass')",
                       (datetime.now(timezone.utc).isoformat(),))
            # Another agent's newer run on the same task is not the nightly check.
            db.execute("INSERT INTO runs VALUES ('task','any-task','keeper',?,'fail')",
                       (datetime.now(timezone.utc).isoformat(),))
        context = json.loads(self.run_boot("--seat", "architect", "--cwd", str(self.cwd),
                                           env={"FOXRUN_TRACKER": str(tracker)}).stdout)
        self.assertIn("(pass), 0 open flags.", context["hookSpecificOutput"]["additionalContext"])

    def test_no_nightly_line_without_a_handoff_even_with_plist(self):
        self.write("2026-09-26-001-architect-boot.md", note())
        self.install_plist()
        outside = Path(self.folder.name) / "elsewhere"
        outside.mkdir()
        cases = {
            "zero matches": (["--seat", "nobody", "--cwd", str(self.cwd)], ""),
            "no seat": ([], json.dumps({"session_id": "unknown", "cwd": str(self.cwd), "source": "startup"})),
            "cwd outside vault": (["--seat", "architect", "--cwd", str(outside)], ""),
            "vault root, no seat": ([], json.dumps({"session_id": "unknown", "cwd": str(self.vault), "source": "startup"})),
        }
        for name, (args, stdin) in cases.items():
            with self.subTest(name):
                result = self.run_boot(*args, stdin=stdin)
                self.assertEqual((result.returncode, result.stdout), (0, ""))
        # The same plist does print the line when a handoff is printed.
        context = json.loads(self.run_boot("--seat", "architect", "--cwd", str(self.cwd)).stdout)
        self.assertIn("Nightly check has never run", context["hookSpecificOutput"]["additionalContext"])

    def test_nightly_last_run_and_unanswered_flags(self):
        self.write("2026-09-26-001-architect-boot.md", note())
        ended = datetime.now(timezone.utc).isoformat()
        database = self.nightly_db(ended)
        with sqlite3.connect(database) as db:
            db.executemany("INSERT INTO comments VALUES (?,?,?,?,?,?)", [
                (1, "task", "T289", "session-nightly", ended,
                 "Flag: unpromoted @Person@ words, 501192e0 2026-09-29 13:07 EDT: define each table (Jev 0.800)"),
                (2, "task", "T123", "session-nightly", ended,
                 "Flag: unpromoted @Person@ words, 11111111 2026-09-29 13:08 EDT: keep this exact standing rule for all future sessions please (Jev 0.600)"),
                (3, "task", "T123", "agent", (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat(),
                 "@Person@: keep this exact standing rule for all future sessions please."),
            ])
        context = json.loads(self.run_boot("--seat", "architect", "--cwd", str(self.cwd)).stdout)
        context = context["hookSpecificOutput"]["additionalContext"]
        self.assertIn("(pass), 1 open flags.", context)
        self.assertIn("Flag: unpromoted T289: define each table", context)
        self.assertNotIn("Flag: unpromoted T123", context)

    def test_unrelated_later_comment_does_not_answer_flag(self):
        self.write("2026-09-26-001-architect-boot.md", note())
        ended = datetime.now(timezone.utc).isoformat()
        database = self.nightly_db(ended)
        later = (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat()
        with sqlite3.connect(database) as db:
            db.executemany("INSERT INTO comments VALUES (?,?,?,?,?,?)", [
                (10, "task", "T289", "session-nightly", ended,
                 "Flag: unpromoted @Person@ words, s 2026-09-29 13:07 EDT: define what each table holds in one sentence for every workspace (Jev 0.800)"),
                (11, "task", "T289", "agent", later, "Status: I checked the PR."),
            ])
        result = json.loads(self.run_boot("--json", "--seat", "architect", "--cwd", str(self.cwd)).stdout)
        self.assertIn("1 open flags", result["nightly_status"][0])
        with sqlite3.connect(database) as db:
            db.execute("INSERT INTO comments VALUES (?,?,?,?,?,?)",
                       (12, "task", "T289", "agent", later, "See flag comment 10; the words are recorded."))
        result = json.loads(self.run_boot("--json", "--seat", "architect", "--cwd", str(self.cwd)).stdout)
        self.assertIn("0 open flags", result["nightly_status"][0])

    def test_later_decision_quote_answers_flag(self):
        self.write("2026-09-26-001-architect-boot.md", note())
        ended = datetime.now(timezone.utc).isoformat()
        database = self.nightly_db(ended)
        later = (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat()
        with sqlite3.connect(database) as db:
            db.execute("INSERT INTO comments VALUES (?,?,?,?,?,?)",
                       (10, "task", "T289", "session-nightly", ended,
                        "Flag: unpromoted @Person@ words, s 2026-09-29 13:07 EDT: define what each table holds in one sentence for every workspace (Jev 0.800)"))
            db.execute("CREATE TABLE decisions(person_words TEXT,source TEXT,decided_on TEXT)")
            db.execute("INSERT INTO decisions VALUES (?,?,?)",
                       ("define what each table holds in one sentence for every workspace", "", later))
        result = json.loads(self.run_boot("--json", "--seat", "architect", "--cwd", str(self.cwd)).stdout)
        self.assertIn("0 open flags", result["nightly_status"][0])

    def test_nightly_failed_and_stale_warnings(self):
        self.write("2026-09-26-001-architect-boot.md", note())
        old = (datetime.now(timezone.utc) - timedelta(hours=31)).isoformat()
        database = self.nightly_db(old, "fail")
        context = json.loads(self.run_boot("--seat", "architect", "--cwd", str(self.cwd)).stdout)
        self.assertIn("Nightly check failed", context["hookSpecificOutput"]["additionalContext"])
        with sqlite3.connect(database) as db:
            db.execute("UPDATE runs SET result='pass'")
        context = json.loads(self.run_boot("--seat", "architect", "--cwd", str(self.cwd)).stdout)
        self.assertIn("Nightly check has not run for 31 h", context["hookSpecificOutput"]["additionalContext"])


if __name__ == "__main__":
    unittest.main()
