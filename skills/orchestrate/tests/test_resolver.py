from __future__ import annotations

import itertools
import json
import os
import shlex
import sqlite3
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.support import BIN, ROOT, load_herdr, orchestrate


RUNTIMES = orchestrate.RUNTIMES
ROWS = [key for key, _, _ in orchestrate.ROWS]
HERDR = orchestrate.HERDR_BIN


class GridContractTests(unittest.TestCase):
    def test_eight_rows_three_columns(self) -> None:
        self.assertEqual(len(orchestrate.ROWS), 8)
        self.assertEqual([int(number) for _, number, _ in orchestrate.ROWS], list(range(1, 9)))
        table = orchestrate.grid()
        self.assertEqual(len([line for line in table.splitlines() if line.startswith("| ")]), 9)
        for column in RUNTIMES:
            self.assertIn(f"from {column}", table)

    def test_every_cell_resolves_or_refuses_with_a_replacement(self) -> None:
        for source, want, to in itertools.product(RUNTIMES, ROWS, RUNTIMES):
            with self.subTest(source=source, want=want, to=to):
                result = orchestrate.resolve(source=source, want=want, to=to)
                if result["status"] == "profile_required":
                    self.assertEqual(to, "hermes")
                    self.assertIn(want, orchestrate.HERDR_ROWS)
                    self.assertNotIn("command", result)
                elif result["status"] == "refused":
                    self.assertEqual(to, "hermes")
                    self.assertIn(want, orchestrate.CODE_ROWS)
                    self.assertIn("Hermes child", result["reason"])
                    self.assertTrue(result["use_instead"])
                else:
                    self.assertTrue(result["command"])
                    self.assertIn("ladder", result)
                    self.assertEqual(set(result["ladder"]), {"more_work", "steer", "done"})

    def test_rows_one_to_four_never_open_a_window(self) -> None:
        for source, want, to in itertools.product(RUNTIMES, orchestrate.ONE_SHOT_ROWS, RUNTIMES):
            result = orchestrate.resolve(source=source, want=want, to=to)
            if result["status"] in {"refused", "profile_required"}:
                continue
            with self.subTest(source=source, want=want, to=to):
                self.assertFalse(result["opens_window"])
                self.assertEqual(result["mode"], "one-shot")
                self.assertNotIn("herdr", result["command"])
                self.assertIn("self-closes", result["ladder"]["done"])
                if source != "claude" or to != "codex" or want != "review":
                    self.assertIn(HERDR, result["ladder"]["steer"])

    def test_hosted_rows_go_through_herdr_and_end_with_numbered_close(self) -> None:
        for source, want, to in itertools.product(RUNTIMES, orchestrate.HERDR_ROWS, RUNTIMES):
            result = orchestrate.resolve(source=source, want=want, to=to, session_id="s", hosted=True)
            if result["status"] in {"refused", "profile_required"}:
                continue
            with self.subTest(source=source, want=want, to=to):
                self.assertTrue(result["opens_window"])
                self.assertIn(HERDR, result["command"])
                self.assertIn("close <numbers>", result["ladder"]["done"])
                self.assertIn("--conversation", result["command"])

    def test_hosted_rows_say_so_without_herdr_and_use_the_shelf_herdr_when_it_is_there(self) -> None:
        herdr = Path("/path/without/herdr")
        with patch.object(orchestrate, "HERDR_BIN", str(herdr)):
            grill = orchestrate.resolve(source="codex", want="grill", task="Ask me")
            self.assertEqual(grill["status"], "unavailable")
            self.assertIn(str(herdr), grill["reason"])
            quick = orchestrate.resolve(source="codex", to="claude", want="quick", task="Read it")
            self.assertIn("no session host is installed", quick["ladder"]["steer"])
            with tempfile.TemporaryDirectory() as temporary:
                installed = Path(temporary) / "herdr"
                installed.write_text("#!/bin/sh\n")
                installed.chmod(0o755)
                with patch.object(orchestrate, "HERDR_BIN", str(installed)):
                    grill = orchestrate.resolve(source="codex", want="grill", task="Ask me")
                    self.assertEqual(grill["status"], "resolved")
                    self.assertTrue(grill["command"].startswith(str(installed) + " spawn"))

    def test_person_keys_use_only_person_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            installed = Path(temporary) / "herdr"
            installed.write_text("#!/bin/sh\n")
            installed.chmod(0o755)
            with patch.object(orchestrate, "HERDR_BIN", str(installed)):
                phone = orchestrate.resolve(source="codex", want="converse", to="claude")
                wheel = orchestrate.resolve(source="codex", want="steer", to="claude", hosted=True)
            self.assertIn("person_phone", phone)
            self.assertIn("person_takes_wheel", wheel)
            self.assertEqual([key for key in phone if key.endswith("_phone")], ["person_phone"])
            self.assertEqual([key for key in wheel if key.endswith("_takes_wheel")], ["person_takes_wheel"])

    def test_code_never_goes_to_a_hermes_child(self) -> None:
        for source in RUNTIMES:
            for want in orchestrate.CODE_ROWS:
                result = orchestrate.resolve(source=source, want=want, to="hermes")
                self.assertEqual(result["status"], "refused")
                self.assertNotIn("delegate_task", result["use_instead"])
        advice = orchestrate.resolve(source="hermes", want="advise", to="hermes")
        self.assertIn("delegate_task", advice["command"])

    def test_default_target_rules(self) -> None:
        self.assertEqual(orchestrate.resolve(source="claude", want="fix")["to"], "codex")
        self.assertEqual(orchestrate.resolve(source="hermes", want="parallel")["to"], "codex")
        self.assertEqual(orchestrate.resolve(source="claude", want="advise")["to"], "codex")
        self.assertEqual(orchestrate.resolve(source="codex", want="advise")["to"], "claude")
        self.assertEqual(orchestrate.resolve(source="hermes", want="review")["to"], "claude")
        self.assertEqual(orchestrate.resolve(source="hermes", want="review", to="codex")["to_reason"], "named by the caller")


class LadderTests(unittest.TestCase):
    def test_session_id_turns_one_shots_into_resume_forms(self) -> None:
        claude = orchestrate.resolve(source="codex", want="advise", to="claude", session_id="abc")
        self.assertIn("--resume abc", claude["command"])
        codex = orchestrate.resolve(source="codex", want="fix", to="codex", session_id="abc")
        self.assertIn("codex exec -s workspace-write resume abc --json", codex["command"])
        hermes = orchestrate.resolve(source="claude", want="quick", to="hermes", session_id="abc")
        self.assertIn("chat -Q --resume abc -q", hermes["command"])

    def test_desktop_owned_codex_threads_fork_never_resume(self) -> None:
        result = orchestrate.resolve(source="hermes", want="fix", to="codex", session_id="abc", desktop_owned=True)
        self.assertIn("fork abc", result["command"])
        self.assertNotIn("resume abc", result["command"])
        self.assertTrue(any("fork" in note for note in result["caveats"]))
        steer = orchestrate.resolve(source="claude", want="steer", to="codex", session_id="abc", desktop_owned=True,
                                    hosted=True)
        self.assertIn("resume abc --fork", steer["command"])

    def test_native_desktop_can_steer_existing_thread(self) -> None:
        result = orchestrate.resolve(source="codex", want="fix", to="codex", session_id="abc", desktop_native=True)
        self.assertEqual(result["native_route"], "C")
        self.assertIn("existing desktop thread abc", result["context"])
        self.assertIn("native desktop messaging", result["ladder"]["steer"])

    def test_hosted_steer_without_id_starts_with_runtime_session_search(self) -> None:
        result = orchestrate.resolve(source="claude", want="steer", task="amazon eu", hosted=True)
        self.assertTrue(result["command"].startswith(orchestrate.SEARCH_BIN))
        self.assertIn("who-owns", result["person_takes_wheel"])

    def test_read_only_below_row_four_and_write_tools_on_fix(self) -> None:
        review = orchestrate.resolve(source="codex", want="review", to="claude")
        self.assertIn("--allowedTools Read,Glob,Grep", review["command"])
        fix = orchestrate.resolve(source="codex", want="fix", to="claude")
        self.assertIn("--allowedTools Read,Edit,Write,Bash", fix["command"])
        codex_review = orchestrate.resolve(source="codex", want="review", to="codex")
        self.assertIn("-s read-only", codex_review["command"])

    def test_claude_to_codex_cell_defaults_to_tracked_exec(self) -> None:
        result = orchestrate.resolve(source="claude", want="fix", to="codex", task="fix it")
        self.assertTrue(result["command"].startswith(f"codex exec -m {orchestrate.code_model()}"))
        self.assertIn("/codex:rescue", result["fallback"])
        self.assertEqual(result["start"], "tracked-background")
        follow = orchestrate.resolve(source="claude", want="fix", to="codex", session_id="t1")
        self.assertNotIn("resume", follow["command"])
        self.assertIn("never resume", follow["ladder"]["more_work"])

    def test_claude_to_claude_is_in_process(self) -> None:
        result = orchestrate.resolve(source="claude", want="advise", to="claude")
        self.assertTrue(result["command"].startswith("Agent("))
        self.assertIn("claude -p", result["fallback"])


class HermesCellTests(unittest.TestCase):
    def test_hermes_codex_cells_embed_the_bundled_skill_rules(self) -> None:
        result = orchestrate.resolve(source="hermes", want="fix", to="codex")
        self.assertIn("pty=true", result["command"])
        self.assertIn("background=true", result["command"])
        self.assertIn("danger-full-access", result["command"])
        joined = "\n".join(result["caveats"])
        for needle in ("pty=true", "danger-full-access", "process(action", "thread.started", "git repository"):
            self.assertIn(needle, joined)
        quick = orchestrate.resolve(source="hermes", want="quick", to="codex")
        self.assertNotIn("background=true", quick["command"])

    def test_readers_stay_read_only_from_every_caller(self) -> None:
        # T750 F02: no reader, reviewer, or grader route may ask for unrestricted execution.
        for source, want in itertools.product(RUNTIMES, ("quick", "advise", "review")):
            with self.subTest(source=source, want=want):
                result = orchestrate.resolve(source=source, want=want, to="codex", task="read it")
                self.assertNotIn("danger-full-access", result["command"])
                self.assertNotIn("workspace-write", result["command"])
                self.assertIn("-s read-only", result["command"])
        for want in ("quick", "advise", "review"):
            with self.subTest(builder_access=want):
                command = orchestrate._codex_one_shot(want, "t", None, None, desktop_owned=False, builder_access=True)
                self.assertIn("-s read-only", command)
        hermes_fix = orchestrate.resolve(source="hermes", want="fix", to="codex", task="build it")
        self.assertIn("-s danger-full-access", hermes_fix["command"])
        codex_fix = orchestrate.resolve(source="codex", want="fix", to="codex", task="build it")
        self.assertIn("-s workspace-write", codex_fix["command"])

    def test_codex_result_goes_to_the_run_folder_not_shared_tmp(self) -> None:
        # T750 F07: a fixed /tmp result path collides across runs and can follow a planted link.
        for source, want in itertools.product(("hermes", "codex"), orchestrate.ONE_SHOT_ROWS):
            with self.subTest(source=source, want=want):
                given = orchestrate.resolve(source=source, want=want, to="codex", task="t", run_dir="/runs/x")
                self.assertNotIn("/tmp/", given["command"])
                self.assertIn("-o /runs/x/result.md", given["command"])
                blank = orchestrate.resolve(source=source, want=want, to="codex", task="t")
                self.assertNotIn("/tmp/", blank["command"])
                self.assertIn("'<run dir>/result.md'", blank["command"])

    def test_hermes_claude_cells_never_call_bare_claude(self) -> None:
        for want in orchestrate.ONE_SHOT_ROWS:
            result = orchestrate.resolve(source="hermes", want=want, to="claude")
            self.assertIn('terminal(command="claude -p', result["command"])
            self.assertIn("--output-format json", result["command"])
            self.assertIn("timeout=", result["command"])
            self.assertNotIn("pty=true", result["command"])
            joined = "\n".join(result["caveats"])
            self.assertIn("Never call bare `claude`", joined)
            self.assertIn("Keychain", joined)

    def test_hermes_profile_aliases(self) -> None:
        result = orchestrate.resolve(source="claude", want="quick", to="hermes", profile="beta", task="hi")
        self.assertEqual(result["command"], "beta -z hi")
        default = orchestrate.resolve(source="claude", want="quick", to="hermes", task="hi")
        self.assertEqual(default["command"], "hermes -z hi")
        self.assertIn("hermes sessions list --limit 1", default["returns"])


class HermesHostedProfileTests(unittest.TestCase):
    def test_spawn_profiles_use_herdr_role_and_agent_args(self) -> None:
        herdr = load_herdr()
        parser = herdr.build_parser()
        for source, want in itertools.product(("claude", "codex"), ("grill", "converse", "parallel")):
            with self.subTest(source=source, want=want):
                result = orchestrate.resolve(source=source, want=want, to="hermes",
                                             profile="beta", task="Discuss launch", workers=2)
                self.assertEqual(result["status"], "resolved")
                commands = result["command"].split(" ; ")
                self.assertEqual(len(commands), 2 if want == "parallel" else 1)
                for index, command in enumerate(commands, 1):
                    args = parser.parse_args(shlex.split(command)[1:])
                    self.assertEqual(args.command, "spawn")
                    self.assertEqual(args.kind, "hermes")
                    self.assertEqual(args.role, "beta-2" if want == "parallel" and index == 2 else "beta")
                    self.assertEqual(herdr._clean_agent_args(args.agent_args)[:2], ["-p", "beta"])

    def test_profile_resume_uses_herdr_spawn_and_one_shot_fallback(self) -> None:
        herdr = load_herdr()
        parser = herdr.build_parser()
        for source in ("claude", "codex"):
            with self.subTest(source=source):
                with patch.object(orchestrate.shutil, "which", return_value="/usr/local/bin/beta"):
                    result = orchestrate.resolve(source=source, want="steer", to="hermes",
                                                 profile="beta", session_id="hermes-123", task="Continue")
                args = parser.parse_args(shlex.split(result["command"])[1:])
                self.assertEqual(args.command, "spawn")
                self.assertEqual(args.role, "beta")
                self.assertEqual(herdr._clean_agent_args(args.agent_args),
                                 ["-p", "beta", "--resume", "hermes-123"])
                self.assertEqual(result["fallback"], "beta chat -Q --resume hermes-123 -q Continue")
                with patch.object(orchestrate.shutil, "which", return_value=None):
                    fallback = orchestrate.resolve(source=source, want="steer", to="hermes",
                                                    profile="beta", session_id="hermes-123", task="Continue")
                self.assertEqual(fallback["fallback"],
                                 "hermes -p beta chat -Q --resume hermes-123 -q Continue")

    def test_missing_or_invalid_profile_never_returns_bad_herdr_command(self) -> None:
        for source, want in itertools.product(("claude", "codex"), orchestrate.HERDR_ROWS):
            with self.subTest(source=source, want=want):
                result = orchestrate.resolve(source=source, want=want, to="hermes")
                if want == "parallel":
                    self.assertEqual(result["status"], "refused")
                else:
                    self.assertEqual(result["status"], "profile_required")
                    self.assertNotIn("command", result)
        with self.assertRaises(orchestrate.ResolveError):
            orchestrate.resolve(source="claude", want="converse", to="hermes", profile="bad profile")


class ClaudeRoutesTests(unittest.TestCase):
    def test_default_one_shots_have_exact_commands(self) -> None:
        for want, sandbox in (("quick", "-s read-only"), ("advise", "-s read-only"), ("fix", "--sandbox danger-full-access")):
            with self.subTest(want=want):
                result = orchestrate.resolve(source="claude", want=want, to="codex", task="do work",
                                             cwd="/tmp/repo", run_dir="/tmp/run")
                self.assertEqual(result["command"],
                    f"codex exec -m {orchestrate.code_model()} -c model_reasoning_effort=high -c service_tier=priority "
                    f'{sandbox} -C "/tmp/repo" --json -o "/tmp/run/result.md" "do work" '
                    '</dev/null > "/tmp/run/events.jsonl" 2>&1')
                self.assertEqual(result["start"], "tracked-background")
                self.assertNotIn("/codex:rescue", result["command"])

    def test_builders_get_full_access_and_reviewers_stay_read_only(self) -> None:
        for want in orchestrate.CODE_ROWS:
            with self.subTest(want=want):
                result = orchestrate.resolve(source="claude", want=want, to="codex", task="build it")
                self.assertIn("--sandbox danger-full-access", result["command"])
                self.assertNotIn("workspace-write", result["command"])
        for want in ("quick", "advise", "review"):
            with self.subTest(want=want):
                result = orchestrate.resolve(source="claude", want=want, to="codex", task="read it")
                self.assertIn("-s read-only", result["command"])
                self.assertNotIn("danger-full-access", result["command"])

    def test_thread_route_has_exact_queue_command_and_watcher(self) -> None:
        result = orchestrate.resolve(source="claude", want="steer", to="codex", thread="123-abc", task="next turn")
        self.assertEqual(result["command"], 'codex queue --thread 123-abc --message "next turn"')
        self.assertEqual(result["start"], "tracked-background")
        watcher = result["watcher"]
        self.assertIn('state_db=${ORCHESTRATE_CODEX_STATE_DB:-$HOME/.codex/state_5.sqlite}', watcher)
        self.assertIn('queue_db=${ORCHESTRATE_CODEX_QUEUE_DB:-$HOME/.codex/queue_1.sqlite}', watcher)
        self.assertIn('sqlite3 -readonly "$state_db" "select rollout_path from threads where id=\'123-abc\'"', watcher)
        self.assertIn('sqlite3 -readonly "$queue_db" "select count(*) from queued_items where thread_id=\'123-abc\'"', watcher)
        self.assertIn("before=$(grep -c", watcher)
        self.assertIn("after=$(grep -c", watcher)
        self.assertIn("sleep 2", watcher)
        self.assertIn("+ 1800", watcher)
        self.assertIn("exit 1", watcher)
        self.assertTrue(any("plain shell &" in caveat for caveat in result["caveats"]))
        self.assertTrue(any("loaded this thread since launch" in caveat for caveat in result["caveats"]))

    def test_caveats_have_no_duplicate_entries(self) -> None:
        cases = [dict(source=source, want=want, to=to)
                 for source, want, to in itertools.product(RUNTIMES, ROWS, RUNTIMES)]
        for want in ROWS:
            cases += [dict(source="claude", want=want, to="codex", thread="123-abc"),
                      dict(source="claude", want=want, to="codex", new_thread="worker"),
                      dict(source="claude", want=want, to="codex", watch=True)]
        for args in cases:
            with self.subTest(args=args):
                caveats = orchestrate.resolve(**args).get("caveats", [])
                self.assertEqual(len(caveats), len(set(caveats)))

    def test_watcher_waits_for_own_queue_to_drain(self) -> None:
        thread_id = "123-abc"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            rollout = root / "rollout.jsonl"
            rollout.write_text("", encoding="utf-8")
            state_db = root / "state.sqlite"
            queue_db = root / "queue.sqlite"
            with sqlite3.connect(state_db) as db:
                db.execute("create table threads (id text, rollout_path text)")
                db.execute("insert into threads values (?, ?)", (thread_id, str(rollout)))
            with sqlite3.connect(queue_db) as db:
                db.execute("create table queued_items (thread_id text)")
                db.execute("insert into queued_items values (?)", (thread_id,))
            watcher = orchestrate.resolve(source="claude", want="steer", to="codex",
                                           thread=thread_id)["watcher"]
            env = {**os.environ, "ORCHESTRATE_CODEX_STATE_DB": str(state_db),
                   "ORCHESTRATE_CODEX_QUEUE_DB": str(queue_db)}
            process = subprocess.Popen(watcher, shell=True, executable="/bin/sh", env=env,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                time.sleep(0.2)
                with rollout.open("a", encoding="utf-8") as stream:
                    stream.write('{"type":"task_complete"}\n')
                time.sleep(2.2)
                self.assertIsNone(process.poll(), "a completed unrelated turn must not clear the queue")
                with sqlite3.connect(queue_db) as db:
                    db.execute("delete from queued_items where thread_id=?", (thread_id,))
                stdout, stderr = process.communicate(timeout=5)
                self.assertEqual((process.returncode, stdout, stderr), (0, "", ""))
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.communicate(timeout=5)

    def test_new_thread_route_creates_then_queues_with_tracked_watcher(self) -> None:
        result = orchestrate.resolve(source="claude", want="quick", to="codex",
                                     new_thread="My Thread", task="do work", cwd="/tmp/repo")
        self.assertEqual(result["command"],
                         '~/.foxrun/skills/orchestrate/bin/orchestrate codex-thread --name "My Thread" --cwd "/tmp/repo" --prompt "do work"')
        self.assertEqual(result["next_command"],
                         'codex queue --thread <new-thread-id> --message "<follow-up message>"')
        self.assertIn("<new-thread-id>", result["watcher"])
        self.assertEqual(result["start"], "tracked-background")
        self.assertTrue(any("before the queue send" in item for item in result["caveats"]))
        self.assertTrue(any("already sends the first prompt" in item for item in result["caveats"]))

    def test_watch_alias_uses_task_as_thread_name(self) -> None:
        result = orchestrate.resolve(source="claude", want="quick", to="codex",
                                     watch=True, task="do work", cwd="/tmp/repo")
        self.assertEqual(result["command"],
                         '~/.foxrun/skills/orchestrate/bin/orchestrate codex-thread --name "do work" --cwd "/tmp/repo" --prompt "do work"')
        self.assertIn("codex queue", result["next_command"])

    def test_new_thread_and_watch_commands_use_installed_helper_path(self) -> None:
        for options in ({"new_thread": "My Thread"}, {"watch": True}):
            with self.subTest(options=options):
                result = orchestrate.resolve(source="claude", want="quick", to="codex",
                                             task="do work", cwd="/tmp/repo", **options)
                self.assertTrue(result["command"].startswith(
                    "~/.foxrun/skills/orchestrate/bin/orchestrate codex-thread "))

    def test_review_and_design_have_exact_commands(self) -> None:
        review = orchestrate.resolve(source="claude", want="review", to="codex", task="review code")
        design = orchestrate.resolve(source="claude", want="review", to="codex", task="review design", design=True)
        self.assertEqual(review["command"], "codex exec -s read-only review")
        self.assertEqual(review["fallback"], "/codex:review")
        self.assertEqual(design["command"], "/codex:adversarial-review")
        self.assertEqual(review["start"], "tracked-background")
        for result in (review, design):
            self.assertIn("reviewer model", result["returns"])

    def test_hosted_claude_herdr_spawn_has_no_background_start(self) -> None:
        result = orchestrate.resolve(source="claude", to="codex", want="parallel", workers=2, hosted=True)
        self.assertIn("herdr spawn", result["command"])
        self.assertNotIn("start", result)

    def test_design_plugin_review_has_no_background_start(self) -> None:
        result = orchestrate.resolve(source="claude", to="codex", want="review", design=True)
        self.assertEqual(result["command"], "/codex:adversarial-review")
        self.assertNotIn("start", result)

    def test_claude_review_ladder_uses_new_runs_without_steering(self) -> None:
        for design in (False, True):
            with self.subTest(design=design):
                result = orchestrate.resolve(source="claude", to="codex", want="review", design=design)
                self.assertEqual(result["ladder"]["steer"], "no outside route steers a running turn")
                self.assertEqual(result["ladder"]["more_work"],
                                 "new run and new brief for each fix round; never resume")

    def test_parallel_default_and_hosted_exact_commands(self) -> None:
        default = orchestrate.resolve(source="claude", want="parallel", to="codex", workers=2,
                                      cwd="/tmp/repo", run_dir="/tmp/run")
        expected = [
            f"codex exec -m {orchestrate.code_model()} -c model_reasoning_effort=high -c service_tier=priority "
            f'--sandbox danger-full-access -C "/tmp/repo" --json -o "/tmp/run/worker-{index}/result.md" '
            f'"<brief {index}: disjoint file scope>" </dev/null > "/tmp/run/worker-{index}/events.jsonl" 2>&1'
            for index in (1, 2)
        ]
        self.assertEqual(default["command"], " ; ".join(expected))
        self.assertEqual(default["start"], "tracked-background")
        hosted = orchestrate.resolve(source="claude", want="parallel", to="codex", workers=2, hosted=True,
                                     cwd="/tmp/repo", conversation="claude:lead")
        self.assertEqual(hosted["command"],
            "~/.foxrun/skills/herdr/bin/herdr spawn --kind codex --role worker-1 --cwd /tmp/repo "
            "--conversation claude:lead -- <brief 1: disjoint file scope> ; "
            "~/.foxrun/skills/herdr/bin/herdr spawn --kind codex --role worker-2 --cwd /tmp/repo "
            "--conversation claude:lead -- <brief 2: disjoint file scope>")
        self.assertNotIn("start", hosted)

    def test_no_thread_id_never_queues_and_fork_caveat_scope(self) -> None:
        for want in ROWS:
            with self.subTest(want=want):
                result = orchestrate.resolve(source="claude", want=want, to="codex")
                self.assertNotIn("codex queue", json.dumps(result))
        queue = orchestrate.resolve(source="claude", want="steer", to="codex", thread="abc", desktop_owned=True)
        self.assertFalse(any("fork" in caveat.lower() for caveat in queue["caveats"]))
        resume = orchestrate.resolve(source="codex", want="fix", to="codex", session_id="abc", desktop_owned=True)
        hosted = orchestrate.resolve(source="claude", want="steer", to="codex", session_id="abc",
                                     desktop_owned=True, hosted=True)
        self.assertTrue(any("fork" in caveat.lower() for caveat in resume["caveats"]))
        self.assertTrue(any("fork" in caveat.lower() for caveat in hosted["caveats"]))

    def test_every_claude_worker_or_watcher_route_has_tracked_start(self) -> None:
        for want, to in itertools.product(ROWS, RUNTIMES):
            result = orchestrate.resolve(source="claude", want=want, to=to)
            if result["status"] == "refused" or want in orchestrate.HERDR_ROWS:
                continue
            with self.subTest(want=want, to=to):
                self.assertEqual(result["start"], "tracked-background")
        queue = orchestrate.resolve(source="claude", want="quick", to="codex", thread="abc")
        self.assertEqual(queue["start"], "tracked-background")

    def test_cli_new_flags(self) -> None:
        completed = subprocess.run([str(BIN), "resolve", "--from", "claude", "--want", "steer", "--to", "codex",
                                    "--thread", "abc", "--task", "next"], capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(completed.stdout)["command"], 'codex queue --thread abc --message "next"')


class ResolverNoRegressionTests(unittest.TestCase):
    def test_codex_and_hermes_match_unmodified_resolver(self) -> None:
        cases = json.loads((Path(__file__).with_name("resolver_baseline.json")).read_text(encoding="utf-8"))
        for case in cases:
            with self.subTest(args=case["args"]):
                if (case["args"].get("to") == "hermes"
                        and case["args"].get("want") in orchestrate.HERDR_ROWS
                        and case["output"]["status"] != "refused"):
                    result = orchestrate.resolve(**case["args"])
                    self.assertEqual(result["status"], "profile_required")
                    self.assertNotIn("command", result)
                    continue
                self.assertEqual(orchestrate.resolve(**case["args"]), case["output"])
        hermes = orchestrate.resolve(source="hermes", want="fix", to="codex")
        self.assertIn('background=true', hermes["command"])
        self.assertTrue(any('process(action="poll"' in note for note in hermes["caveats"]))
        desktop = orchestrate.resolve(source="codex", want="fix", desktop_native=True)
        self.assertEqual(desktop["native_route"], "C")


class CodexDesktopNativeTests(unittest.TestCase):
    def test_c_is_default_and_check_selects_d(self) -> None:
        default = orchestrate.resolve(source="codex", want="advise", desktop_native=True)
        check = orchestrate.resolve(source="codex", want="advise", desktop_native=True, check=True)
        self.assertEqual((default["to"], default["native_route"]), ("codex", "C"))
        self.assertEqual(check["native_route"], "D")

    def test_all_native_routes_are_available_with_four_separate_choices(self) -> None:
        for route in orchestrate.NATIVE_ROUTES:
            with self.subTest(route=route):
                result = orchestrate.resolve(source="codex", want="fix", to="codex", desktop_native=True,
                                             native_route=route)
                self.assertEqual(result["native_route"], route)
                for key in ("worker_type", "context", "waiting", "notification"):
                    self.assertTrue(result[key])
                self.assertIn("unverified", result)

    def test_c_brief_has_the_return_contract(self) -> None:
        result = orchestrate.resolve(source="codex", want="fix", desktop_native=True)
        brief = "\n".join(result["brief_template"])
        for text in ("Task, workspace", "Worker thread ID", "Lead return thread ID", "Model:", "Effort:",
                     "Failure boundary", "one completion message", "Stop after that message"):
            self.assertIn(text, brief)

    def test_each_caller_to_codex_keeps_its_supported_route(self) -> None:
        claude = orchestrate.resolve(source="claude", want="fix", to="codex")
        hermes = orchestrate.resolve(source="hermes", want="fix", to="codex")
        codex_cli = orchestrate.resolve(source="codex", want="fix", to="codex")
        codex_desktop = orchestrate.resolve(source="codex", want="fix", to="codex", desktop_native=True)
        self.assertIn("codex exec", claude["command"])
        self.assertIn("codex exec", hermes["command"])
        self.assertIn("codex exec", codex_cli["command"])
        self.assertNotIn("codex exec", codex_desktop["command"])
        self.assertNotIn("herdr", codex_desktop["command"])

    def test_each_caller_destination_pair_resolves_with_desktop_scope(self) -> None:
        for source, destination in itertools.product(RUNTIMES, RUNTIMES):
            with self.subTest(source=source, destination=destination):
                result = orchestrate.resolve(source=source, want="advise", to=destination,
                                             desktop_native=source == "codex")
                self.assertEqual(result["to"], destination)
                if source == destination == "codex":
                    self.assertEqual(result["native_route"], "C")
                else:
                    self.assertNotEqual(result["mode"], "codex-desktop-native")

    def test_hosted_request_keeps_herdr_available(self) -> None:
        result = orchestrate.resolve(source="codex", want="converse", to="codex", desktop_native=True, hosted=True)
        self.assertIn(orchestrate.HERDR_BIN, result["command"])

    def test_cli_native_flags(self) -> None:
        completed = subprocess.run(
            [str(BIN), "resolve", "--from", "codex", "--want", "fix", "--desktop-native", "--check"],
            capture_output=True, text=True, check=True,
        )
        self.assertEqual(json.loads(completed.stdout)["native_route"], "D")


class CliTests(unittest.TestCase):
    def test_cli_resolve_prints_json(self) -> None:
        completed = subprocess.run(
            [str(BIN), "resolve", "--from", "codex", "--want", "advise", "--task", "is this sound?"],
            capture_output=True, text=True, check=True,
        )
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["row"], 2)
        self.assertEqual(payload["to"], "claude")

    def test_cli_refuses_unknown_row(self) -> None:
        completed = subprocess.run(
            [str(BIN), "resolve", "--from", "codex", "--want", "dance"], capture_output=True, text=True,
        )
        self.assertNotEqual(completed.returncode, 0)

    def test_cli_grid_and_rows(self) -> None:
        grid = subprocess.run([str(BIN), "grid", "--from", "hermes"], capture_output=True, text=True, check=True)
        self.assertIn("| 8 | parallel workers |", grid.stdout)
        rows = subprocess.run([str(BIN), "rows"], capture_output=True, text=True, check=True)
        self.assertEqual(len(json.loads(rows.stdout)), 8)


class SkillDocTests(unittest.TestCase):
    def test_skill_names_every_row_and_column(self) -> None:
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        for _, _, name in orchestrate.ROWS:
            self.assertIn(name.split(" (")[0], text)
        for column in RUNTIMES:
            self.assertIn(column, text)
        self.assertIn("never open a window", text)
        self.assertIn("Code never goes to a Hermes child", text)
        self.assertIn("fork, never resume", text)
        self.assertIn("Worker thread with reply", text)
        self.assertIn("fast mode on native threads", text)
        for retired in ("fleet", "foxy", "dex", "claude-delegate"):
            self.assertIn(retired, text)

    def test_skill_has_no_dangling_doctrine_pointer(self) -> None:
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertNotIn("agent-family-routing", text)


if __name__ == "__main__":
    unittest.main()


class ModelPolicyTests(unittest.TestCase):
    def test_code_model_changes_without_editing_resolver(self):
        import copy
        from base.agent_catalog import model_policy
        original = model_policy()
        alternative = original['tiers']['work']['codex']['model']
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            (home / 'config').mkdir()
            changed = copy.deepcopy(original)
            changed['tiers']['code']['codex']['model'] = alternative
            (home / 'config/models.yaml').write_text(json.dumps(changed))
            with patch.dict(os.environ, FOXRUN_HOME=str(home)):
                result = orchestrate.resolve(source='claude', want='fix', to='codex')
                self.assertEqual(shlex.split(result['command'])[3], alternative)
                changed['tiers']['code']['codex']['model'] = original['banned'][0]
                (home / 'config/models.yaml').write_text(json.dumps(changed))
                with self.assertRaises(ValueError):
                    orchestrate.resolve(source='claude', want='fix', to='codex')
