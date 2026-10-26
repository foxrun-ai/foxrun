"""The run-trail transfer receipt is written through a new private file."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from base import run_trails  # noqa: E402


class ReceiptTests(unittest.TestCase):
    def test_receipt_never_writes_through_a_link_at_the_old_temporary_name(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            outside = root / "outside.txt"
            outside.write_text("keep")
            receipt = root / "run-transfer.json"
            link = root / "run-transfer.json.tmp"
            link.symlink_to(outside)
            run_trails.record(receipt, {"state": "planned"})
            run_trails.record(receipt, {"state": "source-held"})
            self.assertEqual(outside.read_text(), "keep")
            self.assertTrue(link.is_symlink())
            self.assertEqual(json.loads(receipt.read_text()), {"state": "source-held"})
            self.assertEqual(receipt.stat().st_mode & 0o777, 0o600)
            self.assertEqual(sorted(p.name for p in root.iterdir()), ["outside.txt", "run-transfer.json", "run-transfer.json.tmp"])


if __name__ == "__main__":
    unittest.main()
