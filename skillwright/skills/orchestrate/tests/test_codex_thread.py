from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

from tests.support import orchestrate


THREAD_ID = "01a0cad3-81a5-7480-bd69-add1024f7327"
STUB = '''#!/usr/bin/env python3
import json, os, sys
with open(os.environ["STUB_LOG"], "w") as log:
    for line in sys.stdin:
        message = json.loads(line)
        log.write(json.dumps(message) + "\\n")
        log.flush()
        method = message["method"]
        if method == "initialize":
            reply = {"id": message["id"], "result": {}}
        elif method == "thread/start":
            reply = {"id": message["id"], "result": {"thread": {"id": "''' + THREAD_ID + '''"}}}
        elif method == "thread/name/set":
            reply = {"id": message["id"], "result": {}}
        elif method == "turn/start":
            if os.environ.get("STUB_STALL"):
                continue
            reply = {"id": message["id"], "result": {"turn": {"id": "turn-1"}}}
            print(json.dumps(reply), flush=True)
            reply = {"method": "turn/completed", "params": {"threadId": "''' + THREAD_ID + '''"}}
        else:
            continue
        print(json.dumps(reply), flush=True)
'''


class CodexThreadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.stub = self.root / "codex"
        self.stub.write_text(STUB, encoding="utf-8")
        self.stub.chmod(0o755)
        self.log = self.root / "messages.jsonl"
        self.db = self.root / "state.sqlite"
        with contextlib.closing(sqlite3.connect(self.db)) as db, db:
            db.execute("create table threads (id text, name text, source text, rollout_path text)")
        self.env = mock.patch.dict(os.environ, {"PATH": f"{self.root}:{os.environ['PATH']}",
                                               "STUB_LOG": str(self.log),
                                               "ORCHESTRATE_CODEX_STATE_DB": str(self.db)}, clear=False)
        self.env.start()
        self.addCleanup(self.env.stop)

    def add_thread(self, *, source: str = "vscode", name: str = "My Thread") -> None:
        with contextlib.closing(sqlite3.connect(self.db)) as db, db:
            db.execute("insert into threads values (?, ?, ?, ?)",
                       (THREAD_ID, name, source, str(self.root / "rollout.jsonl")))

    def invoke(self, *, running: bool = True, timeout: str = "2") -> tuple[int, str, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.object(orchestrate, "_codex_app_running", return_value=running), \
             contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = orchestrate.main(["codex-thread", "--name", "My Thread", "--cwd", str(self.root),
                                     "--prompt", "First message", "--model", orchestrate.code_model(),
                                     "--sandbox", "workspace-write", "--timeout", timeout])
        return code, stdout.getvalue(), stderr.getvalue()

    def test_success_uses_tested_protocol_and_prints_one_json_line(self) -> None:
        self.add_thread()
        code, stdout, stderr = self.invoke()
        self.assertEqual((code, stderr), (0, ""))
        self.assertEqual(len(stdout.splitlines()), 1)
        self.assertEqual(json.loads(stdout), {"thread_id": THREAD_ID, "name": "My Thread",
                                               "cwd": str(self.root),
                                               "rollout_path": str(self.root / "rollout.jsonl")})
        messages = [json.loads(line) for line in self.log.read_text().splitlines()]
        self.assertEqual([item["method"] for item in messages],
                         ["initialize", "initialized", "thread/start", "thread/name/set", "turn/start"])
        self.assertEqual(messages[0]["params"]["clientInfo"],
                         {"title": "Codex Plugin", "name": "Claude Code", "version": "t167"})
        self.assertEqual(messages[2]["params"], {"cwd": str(self.root), "model": orchestrate.code_model(),
                                                  "approvalPolicy": "never", "sandbox": "workspace-write",
                                                  "ephemeral": False})
        self.assertEqual(messages[3]["params"], {"threadId": THREAD_ID, "name": "My Thread"})
        self.assertEqual(messages[4]["params"]["input"],
                         [{"type": "text", "text": "First message", "text_elements": []}])

    def test_app_not_running_fails_before_spawning(self) -> None:
        code, stdout, stderr = self.invoke(running=False)
        self.assertEqual((code, stdout, stderr),
                         (1, "", "Codex app is not running; open Codex and retry.\n"))
        self.assertFalse(self.log.exists())

    def test_missing_thread_fails_on_one_line(self) -> None:
        code, stdout, stderr = self.invoke()
        self.assertEqual((code, stdout, stderr),
                         (1, "", f"Codex did not register the thread {THREAD_ID}; it will not show in the sidebar.\n"))

    def test_non_vscode_thread_fails(self) -> None:
        self.add_thread(source="exec")
        code, stdout, stderr = self.invoke()
        self.assertEqual((code, stdout, stderr),
                         (1, "", f"Codex did not register the thread {THREAD_ID}; it will not show in the sidebar.\n"))

    def test_turn_timeout_fails_on_one_line(self) -> None:
        self.add_thread()
        with mock.patch.dict(os.environ, {"STUB_STALL": "1"}):
            code, stdout, stderr = self.invoke(timeout="0.2")
        self.assertEqual((code, stdout, stderr), (1, "", "Codex turn timed out after 0.2 seconds.\n"))


if __name__ == "__main__":
    unittest.main()
