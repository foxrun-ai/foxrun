import os
import pathlib
import subprocess
import tempfile
import unittest

BIN = pathlib.Path(__file__).resolve().parents[1] / "bin/agent-new"

class WrapperTests(unittest.TestCase):
    def test_missing_installed_program(self):
        with tempfile.TemporaryDirectory() as d:
            env = dict(os.environ, FOXRUN_HOME=d)
            r = subprocess.run([str(BIN), "list"], env=env, capture_output=True, text=True)
            self.assertEqual(r.returncode, 2)
            self.assertIn("agents/tools/agent_new.py not found", r.stderr)

    def test_installed_program_receives_arguments(self):
        with tempfile.TemporaryDirectory() as d:
            tools = pathlib.Path(d, "agents/tools"); tools.mkdir(parents=True)
            (tools / "agent_new.py").write_text("import sys; print('ok', sys.argv[1:])\n")
            env = dict(os.environ, FOXRUN_HOME=d, AGENT_TEAM_PYTHON="python3")
            r = subprocess.run([str(BIN), "list", "--json"], env=env, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0)
            self.assertIn("ok ['list', '--json']", r.stdout)

if __name__ == "__main__":
    unittest.main()
