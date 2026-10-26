from pathlib import Path
import subprocess
import unittest


class NodeBehaviorSuite(unittest.TestCase):
    def test_node_behavior_suite(self):
        root = Path(__file__).resolve().parent.parent
        result = subprocess.run(
            ["node", "--test", *map(str, sorted((root / "tests").glob("*.test.mjs")))],
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
