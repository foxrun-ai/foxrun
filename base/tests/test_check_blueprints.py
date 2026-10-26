
from __future__ import annotations

import sys as _fox_sys
from pathlib import Path as _FoxPath
_fox_root = next(p for p in _FoxPath(__file__).resolve().parents if (p / 'base/core.py').is_file())
_fox_sys.path[:0] = [str(_fox_root / p) for p in ('base', 'work', 'events', 'decisions', 'memory', 'people', 'design', 'capture')]
_fox_sys.path.insert(0, str(_fox_root))
from base.tests.support import setup as _fox_test_setup
_fox_test_setup()
import contextlib
import importlib.util
import io
from pathlib import Path
import sys
import tempfile
import unittest


MODULE_PATH = (Path(__file__).resolve().parent / '../check_blueprints.py')
SPEC = importlib.util.spec_from_file_location("check_blueprints", MODULE_PATH)
checker = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = checker
SPEC.loader.exec_module(checker)


class CheckBlueprintsTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.first = root / "alpha" / "blueprint.sql"
        self.second = root / "beta" / "blueprint.sql"
        self.first.parent.mkdir()
        self.second.parent.mkdir()
        self.first.write_text(
            "CREATE TABLE IF NOT EXISTS parent (id TEXT PRIMARY KEY);\n"
            "CREATE TABLE IF NOT EXISTS child (\n"
            "  id TEXT PRIMARY KEY,\n"
            "  parent_id TEXT REFERENCES missing_parent(id)\n"
            ");\n",
            encoding="utf-8",
        )
        self.second.write_text(
            "CREATE TABLE IF NOT EXISTS parent (id TEXT PRIMARY KEY);\n",
            encoding="utf-8",
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_function_catches_duplicate_and_broken_foreign_key(self):
        findings = checker.check_blueprints([self.first, self.second])
        categories = {finding.category for finding in findings}
        self.assertIn("duplicate_object", categories)
        self.assertIn("broken_foreign_key", categories)

    def test_cli_reports_findings_and_returns_one(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = checker.main([str(self.first), str(self.second)])
        self.assertEqual(1, result)
        self.assertIn("duplicate_object", output.getvalue())
        self.assertIn("broken_foreign_key", output.getvalue())

    def test_declared_metadata_controls_table_mirror_and_trend_checks(self):
        root = Path(self.temp_dir.name) / "metadata"
        root.mkdir()
        blueprint = root / "blueprint.sql"
        blueprint.write_text(
            "CREATE TABLE threads (id TEXT PRIMARY KEY, pulled_at TEXT);\n"
            "CREATE TABLE external_feed (id TEXT PRIMARY KEY);\n"
            "CREATE TABLE observations (id TEXT PRIMARY KEY);\n",
            encoding="utf-8",
        )
        (root / "README.md").write_text(
            "## Collections\n\n"
            "| Collection | Object type | Supertype | Lens | Database type | Who writes it |\n"
            "|---|---|---|---|---|---|\n"
            "| `threads` | thread | database | records | table | local |\n"
            "| `external_feed` | feed | database | records | mirror | feeder |\n"
            "| `observations` | observation | database | history | trend | observer |\n",
            encoding="utf-8",
        )
        findings = checker.check_blueprints([blueprint])
        self.assertFalse(
            any(finding.subject == "threads" and finding.category.startswith("mirror_") for finding in findings)
        )
        self.assertTrue(
            any(finding.subject == "external_feed" and finding.category == "mirror_pulled_at" for finding in findings)
        )
        self.assertTrue(
            any(finding.subject == "observations" and finding.category == "trend_as_of" for finding in findings)
        )

    def test_sqlite_resolves_comma_sources_and_with_ctes(self):
        root = Path(self.temp_dir.name) / "views"
        root.mkdir()
        blueprint = root / "blueprint.sql"
        blueprint.write_text(
            "CREATE TABLE existing (id TEXT PRIMARY KEY);\n"
            "CREATE VIEW bad AS SELECT * FROM existing, missing_table;\n"
            "CREATE VIEW good AS "
            "WITH recent AS (SELECT * FROM existing) SELECT * FROM recent;\n",
            encoding="utf-8",
        )
        findings = checker.check_blueprints([blueprint])
        broken = [finding for finding in findings if finding.category == "broken_view_source"]
        self.assertEqual(["bad"], [finding.subject for finding in broken])
        self.assertIn("missing_table", broken[0].detail)


if __name__ == "__main__":
    unittest.main()
