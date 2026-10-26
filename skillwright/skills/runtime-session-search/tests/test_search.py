from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

from tests.support import BIN, FIXTURES, ROOT, search, stores


CLAUDE_ID = "11111111-1111-4111-8111-111111111111"


def failing_runner(command, **kwargs):
    return subprocess.CompletedProcess(command, 1, "", "fixture command unavailable")


def build_stores(root: Path) -> Path:
    stores = root / "stores"
    claude = stores / ".claude" / "projects" / "-home-example-projects-demo"
    codex = stores / ".codex" / "sessions" / "2026" / "08" / "22"
    hermes = stores / ".hermes"
    helper = hermes / "profiles" / "helper"
    for path in (claude, codex, hermes, helper):
        path.mkdir(parents=True)
    records = [json.loads(line) for line in (FIXTURES / "claude_session.jsonl").read_text().splitlines()]
    with (claude / f"{CLAUDE_ID}.jsonl").open("w") as handle:
        for record in records:
            record["sessionId"] = CLAUDE_ID
            handle.write(json.dumps(record) + "\n")
    shutil.copyfile(
        FIXTURES / "codex_rollout.jsonl",
        codex / "rollout-2026-08-22T14-00-00-codex-session-1.jsonl",
    )
    sql = (FIXTURES / "hermes_state.sql").read_text()
    for database, title, session_id, reply in (
        (hermes / "state.db", "Pricing launch notes", "hermes-session-1", "Pricing launch notes are ready."),
        (helper / "state.db", "Weekly garden plan", "20260101_090000_0000abcd", "The weekly garden plan is drafted."),
    ):
        connection = sqlite3.connect(database)
        connection.executescript(sql.replace("Pricing launch notes are ready.", reply)
                                 .replace("Pricing launch notes", title).replace("hermes-session-1", session_id))
        connection.execute("ALTER TABLE messages ADD COLUMN role TEXT")
        connection.execute("UPDATE messages SET role = 'assistant'")
        connection.execute(
            "INSERT INTO messages (id, session_id, content, role) VALUES (2, ?, ?, 'user')",
            (session_id, f"Draft the {title.lower()}."),
        )
        connection.commit()
        connection.close()
    return stores


class FindTests(unittest.TestCase):
    def test_words_find_sessions_in_all_three_stores_without_a_pane(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store_root = build_stores(Path(temporary))
            result = search.find("pricing launch", stores=stores, stores_root=store_root, since="all",
                                 memex="off", runner=failing_runner, home=Path("/home/example"))
            self.assertEqual(result["status"], "found")
            stores_hit = {hit["store"] for hit in result["hits"]}
            self.assertEqual(stores_hit, {"claude", "codex", "hermes"})
            for hit in result["hits"]:
                self.assertIn("attach_or_resume_cmd", hit)
                self.assertIn("orchestrate_with", hit)
                self.assertIn(hit["store"], hit["read_with"])
            self.assertEqual(result["backend"]["backend"], "builtin")

    def test_hermes_profiles_are_searched_and_labeled(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store_root = build_stores(Path(temporary))
            result = search.find("garden", stores=stores, stores_root=store_root, since="all",
                                 memex="off", runner=failing_runner, runtime="hermes")
            self.assertEqual([hit["profile"] for hit in result["hits"]], ["helper"])
            self.assertIn("hermes -p helper --resume", result["hits"][0]["attach_or_resume_cmd"])

    def test_id_query_ranks_exact_owner_first(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store_root = build_stores(Path(temporary))
            result = search.find(CLAUDE_ID, stores=stores, stores_root=store_root, memex="off", runner=failing_runner)
            self.assertEqual(result["query_kind"], "id")
            self.assertEqual(result["status"], "found")
            self.assertEqual(result["hits"][0]["session_id"], CLAUDE_ID)
            self.assertEqual(result["hits"][0]["store"], "claude")

    def test_missing_match_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store_root = build_stores(Path(temporary))
            result = search.find("nothing like this", stores=stores, stores_root=store_root, since="all",
                                 memex="off", runner=failing_runner)
            self.assertEqual(result["status"], "not_found")
            self.assertEqual(result["hits"], [])

    def test_runtime_filter_limits_stores(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store_root = build_stores(Path(temporary))
            result = search.find("pricing launch", stores=stores, stores_root=store_root, since="all",
                                 memex="off", runner=failing_runner, runtime="codex")
            self.assertEqual({hit["store"] for hit in result["hits"]}, {"codex"})


class MemexTests(unittest.TestCase):
    def test_stale_index_falls_back_to_native_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store_root = build_stores(root)
            index = root / "memex-index"
            index.mkdir()
            (index / "segment").write_text("old")
            old = time.time() - 10 * 86400
            os.utime(index / "segment", (old, old))
            fresh, reason = search.memex_index_fresh(index, store_root)
            self.assertFalse(fresh)
            self.assertEqual(reason, "memex_index_stale")

            # Exercise the real capability check without a host memex install.
            memex_bin = root / "bin" / "memex"
            memex_bin.parent.mkdir()
            memex_bin.touch()
            memex_bin.chmod(0o755)
            memex_commands = []

            def memex_ok_runner(command, **kwargs):
                if command[0] == str(memex_bin):
                    memex_commands.append(command[1:])
                text = "memex 0.11.6" if command[1:] == ["--version"] else "--cwd --limit --source --since --fields"
                return subprocess.CompletedProcess(command, 0, text, "")

            with patch.dict(os.environ, {"PATH": str(memex_bin.parent)}):
                result = search.find("pricing launch", stores=stores, stores_root=store_root, since="all",
                                     memex="auto", memex_index=index, runner=memex_ok_runner,
                                     home=Path("/home/example"))
            self.assertEqual(memex_commands, [["--version"], ["sessions", "--help"], ["search", "--help"]])
            self.assertEqual(result["backend"]["backend"], "builtin")
            self.assertTrue(any("memex_index_stale" in note for note in result["adapter_notes"]))
            self.assertEqual(result["status"], "found")
            self.assertEqual({hit["store"] for hit in result["hits"]}, {"claude", "codex", "hermes"})

    def test_missing_memex_is_reported_not_fatal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store_root = build_stores(Path(temporary))
            result = search.find("pricing launch", stores=stores, stores_root=store_root, since="all",
                                 memex="auto", memex_index=Path(temporary) / "none", runner=failing_runner)
            self.assertEqual(result["backend"]["backend"], "builtin")
            self.assertEqual(result["status"], "found")

    def test_fresh_index_check(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store_root = build_stores(root)
            index = root / "memex-index"
            index.mkdir()
            (index / "segment").write_text("new")
            fresh, reason = search.memex_index_fresh(index, store_root)
            self.assertTrue(fresh)
            self.assertEqual(reason, "memex_index_fresh")


class ReadTests(unittest.TestCase):
    def test_read_claude_final_reply(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store_root = build_stores(Path(temporary))
            result = search.read(CLAUDE_ID, stores=stores, stores_root=store_root)
            self.assertEqual(result["status"], "read")
            self.assertEqual(result["runtime"], "claude")
            self.assertIn("one open approval", result["text"])
            self.assertEqual(result["task_success"], "not_inferred")
            self.assertEqual(result["private_reasoning"], "excluded")
            self.assertEqual(result["resume_with"], f"claude --resume {CLAUDE_ID}")

    def test_read_codex_final_reply(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store_root = build_stores(Path(temporary))
            result = search.read("codex-session-1", stores=stores, stores_root=store_root)
            self.assertEqual(result["runtime"], "codex")
            self.assertIn("validation is complete", result["text"])
            self.assertIn("codex exec resume codex-session-1", result["resume_with"])

    def test_read_hermes_profile_reply(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store_root = build_stores(Path(temporary))
            result = search.read("20260101_090000_0000abcd", stores=stores, stores_root=store_root)
            self.assertEqual(result["runtime"], "hermes")
            self.assertEqual(result["profile"], "helper")
            self.assertIn("garden plan is drafted", result["text"])
            self.assertIn("hermes -p helper --resume", result["resume_with"])

    def test_unknown_id_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store_root = build_stores(Path(temporary))
            result = search.read("99999999-9999-4999-8999-999999999999", stores=stores, stores_root=store_root)
            self.assertEqual(result["status"], "not_found")

    def test_same_id_in_two_hermes_stores_requires_a_choice(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store_root = build_stores(Path(temporary))
            main = store_root / ".hermes" / "state.db"
            connection = sqlite3.connect(main)
            connection.execute("INSERT INTO sessions VALUES ('20260101_090000_0000abcd', 'dup', 1, 2, '/x', 'cli', 3)")
            connection.execute(
                "INSERT INTO messages (id, session_id, content, role) VALUES (9, '20260101_090000_0000abcd', 'dup reply', 'assistant')"
            )
            connection.commit()
            connection.close()
            result = search.read("20260101_090000_0000abcd", stores=stores, stores_root=store_root)
            self.assertEqual(result["status"], "choice_required")
            self.assertEqual({choice["profile"] for choice in result["choices"]}, {"default", "helper"})
            picked = search.read("20260101_090000_0000abcd", stores=stores, stores_root=store_root, profile="helper")
            self.assertEqual(picked["status"], "read")

    def test_output_is_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store_root = build_stores(Path(temporary))
            result = search.read(CLAUDE_ID, stores=stores, stores_root=store_root, max_lines=1, max_bytes=20)
            self.assertLessEqual(len(result["text"].encode()), 20)
            self.assertTrue(result.get("truncated"))


class CliTests(unittest.TestCase):
    def test_cli_find_and_read(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store_root = build_stores(Path(temporary))
            env = {**os.environ, "PATH": "/nonexistent"}
            found = subprocess.run(
                [sys_executable(), str(BIN), "--stores-root", str(store_root), "find", "pricing", "--since", "all", "--memex", "off"],
                capture_output=True, text=True, env=env,
            )
            self.assertEqual(found.returncode, 0, found.stderr)
            payload = json.loads(found.stdout)
            self.assertEqual(payload["status"], "found")
            read = subprocess.run(
                [sys_executable(), str(BIN), "--stores-root", str(store_root), "read", CLAUDE_ID],
                capture_output=True, text=True, env=env,
            )
            self.assertEqual(read.returncode, 0, read.stderr)
            self.assertEqual(json.loads(read.stdout)["runtime"], "claude")

    def test_cli_runs_from_a_shelf_with_no_other_skill(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            shelf = Path(temporary) / "skills"
            shutil.copytree(ROOT, shelf / "runtime-session-search",
                            ignore=shutil.ignore_patterns("tests", "__pycache__"))
            store_root = build_stores(Path(temporary))
            completed = subprocess.run(
                [sys_executable(), str(shelf / "runtime-session-search" / "bin" / "runtime-session-search"),
                 "--stores-root", str(store_root), "find", "pricing", "--since", "all", "--memex", "off"],
                capture_output=True, text=True, env={**os.environ, "PATH": "/nonexistent"},
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(json.loads(completed.stdout)["status"], "found")

    def test_cli_reports_missing_store_readers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            shelf = Path(temporary) / "runtime-session-search"
            shutil.copytree(ROOT, shelf, ignore=shutil.ignore_patterns("tests", "lib", "__pycache__"))
            completed = subprocess.run([sys_executable(), str(shelf / "bin" / "runtime-session-search"), "find", "x"],
                                       capture_output=True, text=True)
            self.assertEqual(completed.returncode, 2)
            self.assertIn("store readers not found", completed.stdout)


def sys_executable() -> str:
    import sys
    return sys.executable


class SkillDocTests(unittest.TestCase):
    def test_skill_states_the_laws(self) -> None:
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        for needle in ("Native files are truth", "choice_required", "not_found", "never closes",
                       "task_success", "orchestrate"):
            self.assertIn(needle, text)


if __name__ == "__main__":
    unittest.main()
