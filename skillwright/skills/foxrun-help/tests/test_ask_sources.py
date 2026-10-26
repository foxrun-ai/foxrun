"""ask-sources checks on labeled fake pages in a temporary home."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "bin" / "ask-sources"


class AskSourcesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / "fake-home"
        self.system = self.root / ".foxrun"
        self.system.mkdir(parents=True)
        (self.system / "DOCUMENTATION.md").write_text(
            "# Documentation (labeled fake)\n\n## ~/.foxrun/hooks\n\nSession hooks run the start page.\n")
        self.workspace = self.root / "foxrun/fake-shop"
        (self.workspace / "notes/deep").mkdir(parents=True)
        (self.root / "foxrun/AGENTS.md").write_text("# Portfolio (labeled fake)\n")
        (self.workspace / "AGENTS.md").write_text("# fake-shop\n\n## Orders\n\nOrders live in the orders table.\n")
        self.env = {**os.environ, "HOME": str(self.root), "FOXRUN_HOME": str(self.system)}

    def ask(self, question, cwd, code=0):
        done = subprocess.run([sys.executable, str(SCRIPT), question, "--cwd", str(cwd)],
                              capture_output=True, text=True, env=self.env, timeout=20)
        self.assertEqual(done.returncode, code, done.stdout + done.stderr)
        return json.loads(done.stdout)

    def test_nearest_agents_wins_over_a_parent(self):
        result = self.ask("where do orders live", self.workspace / "notes/deep")
        self.assertEqual(result["sources"][0]["path"], str(self.workspace / "AGENTS.md"))
        self.assertEqual(result["start_with"], str(self.workspace / "AGENTS.md"))
        self.assertEqual(result["sources"][0]["hits"][0]["section"], "Orders")

    def test_order_is_agents_then_documentation(self):
        result = self.ask("how do hooks run", self.workspace)
        self.assertEqual([item["role"] for item in result["sources"]],
                         ["nearest AGENTS.md", "system DOCUMENTATION.md"])
        self.assertEqual(result["start_with"], str(self.system / "DOCUMENTATION.md"))

    def test_nearest_documentation_is_not_listed_twice(self):
        result = self.ask("hooks", self.system)
        paths = [item["path"] for item in result["sources"]]
        self.assertEqual(paths, [str(self.system / "DOCUMENTATION.md")])

    def test_no_pages_fails_with_a_note(self):
        empty = Path(self.temp.name).resolve() / "elsewhere"
        empty.mkdir()
        done = subprocess.run([sys.executable, str(SCRIPT), "x", "--cwd", str(empty)], capture_output=True,
                              text=True, env={**self.env, "FOXRUN_HOME": str(empty / "none")}, timeout=20)
        self.assertEqual(done.returncode, 1)
        self.assertIn("no AGENTS.md", done.stderr)

    def test_writes_nothing(self):
        before = sorted(p for p in self.root.rglob("*"))
        self.ask("hooks", self.workspace)
        self.assertEqual(before, sorted(p for p in self.root.rglob("*")))


if __name__ == "__main__":
    unittest.main()
